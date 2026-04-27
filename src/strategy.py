#!/usr/bin/env python3

import time
import math
import logging
from dataclasses import dataclass, field
from typing import Optional
from collections import deque


from .order_entry_protocol import Side, OrderReject, ErrorMessage
from .order_book import OrderBookManager
from .order_entry import OrderEntryClient
from .safety import PnLTracker, PositionTracker, ExposureTracker, RiskTracker

log: logging.Logger = logging.getLogger("strategy")

TICK_SIZE: dict[int, int] = {
    1: 10,  # GOLD
    2: 5,  # BLUE
    3: 5,  # KNAN (dorm)
    4: 5,  # STED (dorm)
    5: 5,  # FISH (dorm)
    6: 5,  # DILN (dorm)
    7: 5,  # SORN (dorm)
    8: 5,  # RYAN (dorm)
    9: 5,  # LYON (dorm)
    10: 5,  # WLSH (dorm)
    11: 5,  # LEWI (dorm)
    12: 5,  # BDIN (dorm)
    13: 10,  # UNDY (ETF)
}

HARD_POSITION_LIMIT: int = 10
HARD_PNL_FLOOR: int = -5000


def get_tick(symbol: int) -> int:
    return TICK_SIZE.get(symbol, 5)


def round_tick(price: float, tick: int, side: int) -> int:
    "Buy round down, sell round up"
    if side == Side.BUY:
        return int(math.floor(price / tick) * tick)
    return int(math.ceil(price / tick) * tick)


def weigthed_mid(bid_prc: float, bid_qty: int, ask_prc: float, ask_qty: int) -> float:
    total = bid_qty + ask_qty
    if total == 0:
        return (bid_prc + ask_prc) / 2.0
    imbalance = bid_qty / total
    return bid_prc * (1.0 - imbalance) + ask_prc * imbalance


class ImbalanceSignal:
    __slots__ = "alpha"

    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = alpha

    def signal(
        self, bid_prc: float, bid_qty: int, ask_prc: float, ask_qty: int
    ) -> float:
        mid = (bid_prc + ask_prc) / 2.0
        return self.alpha * (weigthed_mid(bid_prc, bid_qty, ask_prc, ask_qty) - mid)


class TradeImpactSignal:
    def __init__(self) -> None:
        pass


class FairValueEngine:
    def __init__(self) -> None:
        pass


@dataclass(slots=True)
class StrategyConfig:
    base_spread_ticks: int = 1
    max_spread_ticks: int = 4
    volatility_factor: float = 1.5
    soft_position: int = 8
    panic_posiiton: int = 7
    skew_per_unit: float = 0.5
    order_qty: int = 1
    pnl_kill_floor: float = -4500.0
    trade_window: float = 5.0
    aggression_threshold: float = 0.7
    requote_threshold_ticks: int = 1

    symbols: list[int] = field(
        default_factory=lambda: [1, 2]
    )  # testing purposes should up to 13 symbols
    day1_mode: bool = False


@dataclass(slots=True)
class RecentTrade:
    timestamp: float
    symbol: int
    aggressor_side: int
    quantity: int
    price: int


class SymbolState:
    __slots__ = (
        "symbol",
        "tick",
        "bid_order_id",
        "ask_order_id",
        "bid_price",
        "ask_price",
        "fair_value",
        "last_mid",
        "recent_mids",
        "recent_trades",
        "volatility",
        "_next_order_id",
    )

    def __init__(self, symbol: int, start_order_id: int) -> None:
        self.symbol: int = symbol
        self.tick: int = get_tick(symbol)
        self.bid_order_id: Optional[int] = None
        self.ask_order_id: Optional[int] = None
        self.bid_price: int = 0
        self.ask_price: int = 0
        self.fair_value: int = 0
        self.last_mid: float = 0.0
        self.recent_mids: deque[float] = deque(maxlen=100)
        self.recent_trades: deque[RecentTrade] = deque(maxlen=200)
        self.volatility: float = 0.0
        self._next_order_id: int = start_order_id

    def alloc_order_id(self) -> int:
        oid = self._next_order_id
        self._next_order_id += 1
        return oid


class OrderStrategy:
    """market making strategy"""

    __slots__ = (
        "client",
        "manager",
        "enabled",
        "config",
        "exposure_tracker",
        "position_tracker",
        "pnl_tracker",
        "risk_tracker",
        "_killed",
        "_total_volume",
        "state",
    )

    def __init__(
        self,
        client: OrderEntryClient,
        manager: OrderBookManager,
        config: Optional[StrategyConfig] = None,
    ) -> None:
        self.client: OrderEntryClient = client
        self.manager: OrderBookManager = manager
        self.enabled: bool = True
        self.config: StrategyConfig = config or StrategyConfig()
        self.exposure_tracker: ExposureTracker = self.client.exposure_tracker
        self.position_tracker: PositionTracker = self.client.position_tracker
        self.pnl_tracker: PnLTracker = self.client.pnl_tracker
        self.risk_tracker: RiskTracker = self.client.risk_tracker

        self._killed: bool = False
        self._total_volume: int = 0

        self.state: dict[int, SymbolState] = {}
        for sym in self.config.symbols:
            self.state[sym] = SymbolState(symbol=sym, start_order_id=sym * 100_000)

    def stop(self) -> None:
        self.enabled = False
        # TODO: get flat
        self._cancel_all_quotes()

    def on_market_data_update(self) -> None:
        if not self.enabled or self._killed:
            return

        total_pnl = self.pnl_tracker.get_pnl()
        log.info(total_pnl)
        if total_pnl < self.config.pnl_kill_floor:
            log.error(f"PNL kill siwtch tripped pnl: {total_pnl}")
            self._killed = True
            self.stop()
            return

        # TODO: need a way when we kill the program to remeber what we traded and our position, idea is to write the orderstrategy all to disk and then read from disk. should have save method + load method for it.

        # TODO: need to create actual market strategy, this is just a bare bones implementation.

        # TODO: This is a market making strat should be only traded with symbol one and two, need to make mean reversion strat for symbols 2-12 to stat arb symbol 13.
        for sym in self.config.symbols:
            self._step_symbol(sym)

    def on_trade_summary(
        self,
        symbol: int,
        aggressor_side: int,
        quantity: int,
        price: int,
        timestamp: int,
    ) -> None:
        state = self.state.get(symbol)
        if state is None:
            return
        state.recent_trades.append(
            RecentTrade(
                timestamp=timestamp,
                symbol=symbol,
                aggressor_side=aggressor_side,
                quantity=quantity,
                price=price,
            )
        )

    def on_own_fill(self, symbol: int, quantity: int) -> None:
        self._total_volume += quantity

    def _step_symbol(self, symbol: int) -> None:
        book = self.manager.books.get(symbol)
        if book is None:
            return
        bb, bb_qty = book.get_best_bid()
        ba, ba_qty = book.get_best_ask()

        if bb is None or ba is None:
            return

        if bb <= 0 or ba <= 0 or bb > ba:
            return

        if bb_qty <= 0 or ba_qty <= 0:
            return

        state = self.state[symbol]
        cfg = self.config
        tick = state.tick

        # Track mid for volatility
        mid = (bb + ba) / 2.0
        state.recent_mids.append(mid)
        state.last_mid = mid
        fair = self._compute_fair_value(bb, bb_qty, ba, ba_qty, tick)

        # volatility
        state.volatility = self._compute_volatility(state)

        # half spread ticks
        half_spread_ticks = self._compute_half_spread_ticks(state, symbol)
        hafl_spread_px = half_spread_ticks * tick

        # inventory skew
        position = self.client.position_tracker.get_position(symbol)
        skew_ticks = -position * cfg.skew_per_unit
        skew_px = skew_ticks * tick

        # quote prices
        raw_bid = fair - half_spread_ticks + skew_px
        raw_ask = fair + hafl_spread_px + skew_px

        bid_price = round_tick(raw_bid, tick, Side.BUY)
        ask_price = round_tick(raw_ask, tick, Side.SELL)

        # dont cross book
        if bid_price >= ba:
            bid_price = ba - tick
        if ask_price <= bb:
            ask_price = bb - tick

        if bid_price >= ask_price:
            return

        if bid_price <= 0 or ask_price <= 0:
            return

        # position limit guards
        should_bid = (position + cfg.order_qty) <= cfg.soft_position
        should_ask = (position - cfg.order_qty) >= -cfg.soft_position

        # tigthen position
        if position >= cfg.panic_posiiton:
            log.warning("PANIC LONG sym=%d pos=%d — pulling bid", symbol, position)
            should_bid = False
            ask_price = round_tick(fair + tick, tick, Side.SELL)
        elif position <= -cfg.panic_posiiton:
            log.warning("PANIC LONG sym=%d pos=%d — pulling bid", symbol, position)
            should_ask = False
            bid_price = round_tick(fair - tick, tick, Side.BUY)

        # aggressive flow detection
        if self._detect_aggression(state, Side.BUY):
            ask_price += tick
            should_bid = False
        if self._detect_aggression(state, Side.SELL):
            bid_price -= tick
            should_ask = False

        # place orders
        self._manage_quote(state, Side.BUY, bid_price, should_bid)
        self._manage_quote(state, Side.SELL, ask_price, should_ask)

    @staticmethod
    def _compute_fair_value(bb, bb_qty, ba, ba_qty, tick) -> int:
        mid = (bb + ba) / 2.0
        total = bb_qty + ba_qty
        if total == 0:
            return mid

        micro = bb + (ba - bb) * (bb_qty / total)
        max_dev = 0.5 * tick
        return max(mid - max_dev, min(mid + max_dev, micro))

    @staticmethod
    def _compute_volatility(state):
        mids = state.recent_mids
        if len(mids) < 10:
            return 0.0
        prev = mids[0]
        changes: list[float] = []
        for m in list(mids)[1:]:
            changes.append(m - prev)
            prev = m

        if not changes:
            return 0.0
        mean = sum(changes) / len(changes)
        var = sum((c - mean) ** 2 for c in changes) / len(changes)
        return var**0.5

    def _compute_half_spread_ticks(self, state: SymbolState, symbol: int) -> int:
        """Return half-spread as an integer number of ticks"""
        cfg = self.config
        half = float(cfg.base_spread_ticks)

        # add volatility
        vol_ticks = state.volatility / state.tick
        half += vol_ticks * cfg.volatility_factor

        # inventory penatly
        position = self.client.position_tracker.get_position(symbol)
        inventory_ratio = abs(position) / cfg.soft_position
        half += inventory_ratio * 1.5

        # wider spread day one
        if cfg.day1_mode:
            half += 1.0

        return int(round(min(half, float(cfg.max_spread_ticks))))

    def _detect_aggression(self, state: SymbolState, side: int) -> bool:
        cfg = self.config
        now = time.monotonic()
        cutoff = now - cfg.trade_window

        buy_vol: int = 0
        sell_vol: int = 0
        for trade in state.recent_trades:
            if trade.timestamp < cutoff:
                continue
            if trade.aggressor_side == Side.BUY:
                buy_vol += trade.quantity
            else:
                sell_vol += trade.quantity
        total = buy_vol + sell_vol
        if total == 0:
            return False

        if side == Side.BUY:
            return (buy_vol / total) > cfg.aggression_threshold
        return (sell_vol / total) > cfg.aggression_threshold

    def _manage_quote(self, state, side, target_price, should_quote) -> None:
        cfg = self.config
        threshold_px = cfg.requote_threshold_ticks * state.tick

        if side == Side.BUY:
            current_oid = state.bid_order_id
            current_px = state.bid_price
        else:
            current_oid = state.ask_order_id
            current_px = state.ask_price
        if not should_quote:
            if current_oid is not None:
                self._cancel_quote(state, side)
            return

        if current_oid is None:
            self._place_quote(state, side, target_price)
        elif abs(target_price - current_px) >= threshold_px:
            self._modify_quote(state, side, target_price)

    def _place_quote(self, state: SymbolState, side: int, price: int) -> None:
        oid = state.alloc_order_id()
        cfg = self.config

        # Sanity: confirm tick alignment.
        if price % state.tick != 0:
            log.error(
                "INTERNAL: non-tick-aligned price=%d tick=%d sym=%d",
                price,
                state.tick,
                state.symbol,
            )
            return

        responses = self.client.new_order(
            order_id=oid,
            symbol=state.symbol,
            side=side,
            quantity=cfg.order_qty,
            price=price,
        )

        if responses and not self._is_reject(responses[0]):
            if side == Side.BUY:
                state.bid_order_id = oid
                state.bid_price = price
            else:
                state.ask_order_id = oid
                state.ask_price = price
            log.info(
                "QUOTE %s sym=%d oid=%d px=%d qty=%d",
                "BID" if side == Side.BUY else "ASK",
                state.symbol,
                oid,
                price,
                cfg.order_qty,
            )
        else:
            log.warning(
                "QUOTE FAILED %s sym=%d px=%d",
                "BID" if side == Side.BUY else "ASK",
                state.symbol,
                price,
            )

    def _modify_quote(self, state: SymbolState, side: int, new_price: int) -> None:
        # TODO: can change quantity as well so add that next
        cfg = self.config

        if new_price % state.tick != 0:
            log.error("INTERNAL: modify to non-tick price=%d", new_price)
            return

        oid = state.bid_order_id if side == Side.BUY else state.ask_order_id
        if oid is None:
            return

        responses = self.client.modify_order(
            order_id=oid,
            side=side,
            quantity=cfg.order_qty,
            price=new_price,
        )

        if responses and not self._is_reject(responses[0]):
            if side == Side.BUY:
                state.bid_price = new_price
            else:
                state.ask_price = new_price
        else:
            # Modify race conditions: order_entry.py already cleaned its state.
            # We just clear our local tracking.
            log.warning(
                "REQUOTE FAILED %s sym=%d oid=%d — clearing tracking",
                "BID" if side == Side.BUY else "ASK",
                state.symbol,
                oid,
            )
            if side == Side.BUY:
                state.bid_order_id = None
                state.bid_price = 0
            else:
                state.ask_order_id = None
                state.ask_price = 0

    def _cancel_quote(self, state: SymbolState, side: int) -> None:
        oid = state.bid_order_id if side == Side.BUY else state.ask_order_id
        if oid is None:
            return

        self.client.delete_order(oid)

        if side == Side.BUY:
            state.bid_order_id = None
            state.bid_price = 0
        else:
            state.ask_order_id = None
            state.ask_price = 0

    def _cancel_all_quotes(self) -> None:
        for state in self.state.values():
            self._cancel_quote(state, Side.BUY)
            self._cancel_quote(state, Side.SELL)

    @staticmethod
    def _is_reject(resp: object) -> bool:
        return isinstance(resp, (OrderReject, ErrorMessage))


# mean reversion for ETFs


def microprice_calc(orderbook):
    # mean reversion
    best_bid, bid_qty = orderbook.book.get_best_bid()
    best_ask, ask_qty = orderbook.book.get_best_ask()
    return (best_bid * ask_qty)(best_ask * bid_qty) / (
        bid_qty + ask_qty
    )  # double check this equation. i got it from gemini.


# def main():


# spoofing check


# sending spoofing


# market maker; try to keep internal bookeeping of queues for orders we have placed. if too far back in line, cancel.
# IMPORTANT we dont get spoofed so we dont cancel an order we r in good standing for.
# signals that trigger this are important
