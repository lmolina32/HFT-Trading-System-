#!/usr/bin/env python3

import time
from order_entry_protocol import Side
from typing import Dict, Tuple, Optional


class PositionTracker:
    """
    Tracks net position per symbol: total_bought - total_sold. Updated on each fill from the exchange.
    """

    __slots__ = ("symbol_position",)

    def __init__(self):
        self.symbol_position: Dict[int, int] = {}

    def update_position(self, symbol: int, buy_qty: int, sell_qty: int) -> None:
        """Update symbols position by adding (buy quantity - sell quantity)"""
        self.symbol_position[symbol] = (
            self.symbol_position.get(symbol, 0) + buy_qty - sell_qty
        )

    def get_position(self, symbol: int) -> int:
        """Return symbols current position, if not yet traded return 0"""
        return self.symbol_position.get(symbol, 0)


class ExposureTracker:
    """
    Calculates worst-case scenario if all outstanding orders were filled

    Buy Exposure = position + total outstanding buy order quantity
    Sell Exposure = -position + total oustanding sell order quantity"""

    __slots__ = ()

    @staticmethod
    def buy_exposure(
        symbol: int, open_orders: Dict[int, Tuple[int, int, int]], position: int
    ) -> int:
        """Compute buy exposure for given symbol (position + total outstanding buy qty)"""
        outstanding: int = 0
        for sym, side, qty in open_orders.values():
            if sym == symbol and side == Side.BUY:
                outstanding += qty
        return position + outstanding

    @staticmethod
    def sell_exposure(
        symbol: int, open_orders: Dict[int, Tuple[int, int, int]], position: int
    ) -> int:
        """Compute sell exposure for given symbol (-position + total outstanding sell qty)"""
        outstanding: int = 0
        for sym, side, qty in open_orders.values():
            if sym == symbol and side == Side.SELL:
                outstanding += qty
        return -position + outstanding


class PnLTracker:
    __slots__ = ("total_sells", "avg_sell_price", "total_buys", "avg_buy_price")

    def __init__(self) -> None:
        self.total_sells: Dict[int, int] = {}
        self.avg_sell_price: Dict[int, float] = {}
        self.total_buys: Dict[int, int] = {}
        self.avg_buy_price: Dict[int, float] = {}

    def on_fill_buy(self, symbol: int, quantity: int, price: int) -> None:
        """Updated weighted buy price on fill"""
        prev_qty = self.total_buys.get(symbol, 0)
        prev_cost = self.avg_buy_price.get(symbol, 0.0) * prev_qty
        new_qty = prev_qty + quantity
        self.total_buys[symbol] = new_qty
        self.avg_buy_price[symbol] = (prev_cost + quantity * price) / new_qty

    def on_fill_sell(self, symbol: int, quantity: int, price: int) -> None:
        """Updated weighted sell price on fill"""
        prev_qty = self.total_sells.get(symbol, 0)
        prev_rev = self.avg_sell_price.get(symbol, 0.0) * prev_qty
        new_qty = prev_qty + quantity
        self.total_sells[symbol] = new_qty
        self.avg_sell_price[symbol] = (prev_rev + quantity * price) / new_qty

    def get_pnl(self, symbol: int, position: int, market_price: int) -> float:
        buy_cost = self.avg_buy_price.get(symbol, 0.0) * self.total_buys.get(symbol, 0)
        sell_revenue = self.avg_sell_price.get(symbol, 0.0) * self.total_sells.get(
            symbol, 0
        )
        return sell_revenue - buy_cost + (market_price * position)


class RiskTracker:
    __slots__ = (
        "max_qty_per_order",
        "max_qty_per_side",
        "max_exposure",
        "max_orders_per_second",
        "max_per_sequence",
        "max_unacked_orders",
        "position_limit",
        "orders_this_second",
        "last_second_time",
        "orders_this_seq_num",
        "last_seq_num",
    )

    def __init__(self) -> None:
        self.max_qty_per_order: int = 1000
        self.max_qty_per_side: int = 500
        self.max_exposure: int = 1000
        self.max_orders_per_second: int = 10
        self.max_per_sequence: int = 1000
        self.max_unacked_orders: int = 5
        self.position_limit: int = 1000
        self.orders_this_second: int = 0
        self.last_second_time: Optional[float] = None
        self.orders_this_seq_num: int = 0
        self.last_seq_num: Optional[int] = None

    def isValid(
        self,
        symbol: int,
        side: int,
        quantity: int,
        price: int,
        open_orders: Dict[int, Tuple[int, int, int]],
        position_tracker: PositionTracker,
        exposure_tracker: ExposureTracker,
        current_seq_num: int,
    ) -> Tuple[bool, str]:

        if quantity > self.max_qty_per_order:
            return (
                False,
                f"Order quantity {quantity} exceeds maximum allowed {self.max_qty_per_order}",
            )

        if quantity > self.max_qty_per_side:
            return (
                False,
                f"Order quantity {quantity} exceeds maximum allowed per side {self.max_qty_per_side}",
            )

        if side == Side.BUY:
            exposure = exposure_tracker.buy_exposure(
                symbol, open_orders, position_tracker.get_position(symbol)
            )
        else:
            exposure = exposure_tracker.sell_exposure(
                symbol, open_orders, position_tracker.get_position(symbol)
            )
        if exposure + quantity > self.max_exposure:
            return (
                False,
                f"Order would exceed maximum exposure of {self.max_exposure} for symbol {symbol}",
            )

        if price <= 0:  # is this invalid price? anything else?
            return False, "Order price cannot be negative"

        if abs(position_tracker.get_position(symbol)) >= self.position_limit:
            return (
                False,
                f"Order would exceed position limit of {self.position_limit} for symbol {symbol}",
            )

        current_time: float = time.time()
        if self.last_second_time is None or current_time - self.last_second_time >= 1:
            self.orders_this_second = 0  # reset counter if a second has passed
            self.last_second_time = current_time  # update last 'tracked' second to rn
        self.orders_this_second += 1
        if self.orders_this_second > self.max_orders_per_second:
            return (
                False,
                f"exceeded maximum orders per second {self.max_orders_per_second}",
            )

        if current_seq_num != self.last_seq_num:
            self.orders_this_seq_num = 0
            self.last_seq_num = current_seq_num
        self.orders_this_seq_num += 1
        if self.orders_this_seq_num > self.max_per_sequence:
            return (
                False,
                f"Order quantity {quantity} exceeds maximum per sequence {self.max_per_sequence}",
            )

        if len(open_orders) >= self.max_unacked_orders:
            return (
                False,
                f"Number of unacknowledged orders {len(open_orders)} exceeds maximum allowed {self.max_unacked_orders}",
            )

        return True, ""
