#!/usr/bin/env python3

from __future__ import annotations

import heapq
import logging
from typing import Dict, Optional, Tuple, List, TypeAlias
from .market_data_struct import (
    MSG_TYPE,
    SIDE,
    MDHeader,
    NewOrder,
    DeleteOrder,
    ModifyOrder,
    Trade,
    TradeSummary,
    SnapshotInfo,
    PriceLevel,
    BBORecord,
    Order,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log: logging.Logger = logging.getLogger("market_data")
console_handler = logging.StreamHandler()
file_handler = logging.FileHandler("trade_engine.log")
log.addHandler(console_handler)
log.addHandler(file_handler)


trade_body: TypeAlias = (
    NewOrder
    | DeleteOrder
    | ModifyOrder
    | Trade
    | TradeSummary
    | SnapshotInfo
    | MDHeader
)


class OrderBook:
    __slots__ = (
        "symbol",
        "bid_heap",
        "bid_levels",
        "ask_heap",
        "ask_levels",
        "orders",
        "total_volume",
    )

    def __init__(self, symbol: int) -> None:
        self.symbol: int = symbol
        self.bid_heap: List[int] = []
        self.bid_levels: dict[int, PriceLevel] = {}
        self.ask_heap: List[int] = []
        self.ask_levels: dict[int, PriceLevel] = {}
        self.orders: dict[int, Order] = {}
        self.total_volume: int = 0

    def add_order(
        self,
        order_id: int,
        symbol: int,
        side: SIDE,
        qty: int,
        price: int,
        timestamp: int,
    ) -> None:
        if order_id in self.orders:
            raise ValueError(f"[Book {symbol}] Duplicate order id: {order_id}")

        if qty <= 0:
            raise ValueError(
                f"[Book {symbol}] qty={qty} qty <=0 for order id: {order_id}"
            )

        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=qty,
            price=price,
            timestamp=timestamp,
        )

        self.orders[order_id] = order

        if side == SIDE.BUY:
            levels = self.bid_levels
            heap = self.bid_heap
            heap_price = -price
        else:
            levels = self.ask_levels
            heap = self.ask_heap
            heap_price = price

        if price in levels:
            level = levels[price]
            level.total_qty += qty
            level.order_count += 1
        else:
            levels[price] = PriceLevel(price=price, total_qty=qty, order_count=1)
            heapq.heappush(heap, heap_price)

    def delete_order(self, order_id: int) -> None:
        if order_id not in self.orders:
            return
        order = self.orders.pop(order_id)
        if order.side == SIDE.BUY:
            levels = self.bid_levels
        else:
            levels = self.ask_levels
        level = levels[order.price]
        level.total_qty -= order.quantity
        level.order_count -= 1

        # consistency checks
        if level.total_qty < 0:
            raise ValueError(
                f"[Book {self.symbol}] Negative total quantity={level.total_qty}"
                f"price={order.price} after deleting order id {order_id}"
            )
        if level.order_count < 0:
            raise ValueError(
                f"[Book {self.symbol}] Negative order_count={level.order_count}"
                f"price={order.price} after deleting order id {order_id}"
            )
        if level.order_count == 0:
            if level.total_qty != 0:
                raise ValueError(
                    f"[Book {self.symbol}] order_count=0 but total_qty{level.total_qty}"
                    f"at price={order.price}. INCONSISTENT STATE"
                )
            del levels[order.price]

    def trade_order(self, order_id: int, qty: int, price: int) -> None:
        if order_id not in self.orders:
            raise KeyError(
                f"[Book {self.symbol}] trade_oder: order_id={order_id} not found"
            )

        order = self.orders[order_id]

        if order.side == SIDE.BUY:
            levels = self.bid_levels
        else:
            levels = self.ask_levels

        level = levels[order.price]

        order.quantity -= qty
        level.total_qty -= qty
        self.total_volume += qty

        if level.total_qty < 0:
            raise ValueError(
                f"[Book {self.symbol}] Negative total quantity={level.total_qty}"
                f"\nprice={order.price} after trading worder id {order_id}"
            )

        if order.quantity == 0:
            del self.orders[order_id]
            level.order_count -= 1

            if level.order_count < 0:
                raise ValueError(
                    f"[Book {self.symbol}] Negative order_count={level.order_count}"
                    f"price={order.price} after trading order id {order_id}"
                )

            if level.order_count == 0:
                if level.total_qty != 0:
                    raise ValueError(
                        f"[Book {self.symbol}] order_count=0 but total_qty{level.total_qty}"
                        f"at price={order.price}. INCONSISTENT STATE"
                    )
                del levels[order.price]

    def modify_order(self, order_id: int, side: SIDE, qty: int, price: int) -> None:
        if order_id not in self.orders:
            raise KeyError(
                f"[Book {self.symbol}] modify_order: order_id={order_id} not found"
            )

        order = self.orders[order_id]
        symbol = order.symbol
        old_time = order.timestamp

        self.delete_order(order_id)
        self.add_order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            timestamp=old_time,
        )

    def get_best_bid(self) -> Tuple[int, int]:
        self._clear_top_of_bid()
        if not self.bid_heap:
            return (0, 0)
        best_price = -self.bid_heap[0]
        level = self.bid_levels[best_price]
        return (best_price, level.total_qty)

    def get_best_ask(self) -> Tuple[int, int]:
        self._clear_top_of_ask()
        if not self.ask_heap:
            return (0, 0)
        best_price = self.ask_heap[0]
        level = self.ask_levels[best_price]
        return (best_price, level.total_qty)

    def validate(self) -> None:
        """add validation"""
        bb = self.get_best_bid()
        ba = self.get_best_ask()

        if bb is not None and ba is not None and bb[0] >= ba[0]:
            if bb[0] >= ba[0]:
                raise ValueError(
                    f"[Book {self.symbol}] best bid is greater than best ask"
                )

        for label, levels in [("ask", self.ask_levels), ("bid", self.bid_levels)]:
            for px, lvl in levels.items():
                if lvl.total_qty <= 0:
                    raise ValueError(
                        f"[Book {self.symbol}] {label} level at px={px} has qty={lvl.total_qty}"
                    )
                if lvl.order_count <= 0:
                    raise ValueError(
                        f"[Book {self.symbol}] {label} level at px={px} has "
                        f"order_count={lvl.order_count}"
                    )

        for oid, order in self.orders.items():
            expected_levels = (
                self.bid_levels if order.side == SIDE.BUY else self.ask_levels
            )
            side_name = "bid" if order.side == SIDE.BUY else "ask"
            if order.price not in expected_levels:
                raise ValueError(
                    f"[Book {self.symbol}] Order {oid} at {side_name} px={order.price} "
                    f"has no corresponding level"
                )

    def clear(self) -> None:
        """Error -> clear book"""
        self.bid_heap.clear()
        self.bid_levels.clear()
        self.ask_heap.clear()
        self.ask_levels.clear()
        self.orders.clear()

    def _clear_top_of_bid(self) -> None:
        while self.bid_heap and (-self.bid_heap[0]) not in self.bid_levels:
            heapq.heappop(self.bid_heap)

    def _clear_top_of_ask(self) -> None:
        while self.ask_heap and self.ask_heap[0] not in self.ask_levels:
            heapq.heappop(self.ask_heap)

    def __str__(self) -> str:
        bb = self.get_best_bid()
        ba = self.get_best_ask()
        bid_str = f"{bb[0]}x{bb[1]}" if bb else "EMPTY"
        ask_str = f"{ba[0]}x{ba[1]}" if ba else "EMPTY"
        return (
            f"OrderBook(symbol={self.symbol}, "
            f"bid={bid_str}, ask={ask_str}, "
            f"orders={len(self.orders)}), "
            f"volume={self.total_volume}"
        )


class OrderBookManager:
    __slots__ = ("books", "bbo_by_seq")

    def __init__(self) -> None:
        self.books: Dict[int, OrderBook] = {}
        self.bbo_by_seq: Dict[int, BBORecord] = {}

    def get_or_create_book(self, symbol: int) -> OrderBook:
        if symbol not in self.books:
            self.books[symbol] = OrderBook(symbol=symbol)
            log.info(f"{symbol} added to book")
        return self.books[symbol]

    def process_new_order(
        self,
        seq_num: int,
        timestamp: int,
        order_id: int,
        symbol: int,
        side: SIDE,
        qty: int,
        price: int,
        flags: int,
    ) -> None:
        if flags != 0:
            log.warning(
                f"seq={seq_num}: NEW_ORDER flags={flags} != 0 for order_id={order_id}"
            )
        book = self.get_or_create_book(symbol)
        book.add_order(order_id, symbol, side, qty, price, timestamp)
        self._log_bbo(book, seq_num)

    def process_delete_order(self, seq_num: int, order_id: int) -> None:
        book = self._find_book(order_id, "DELETE_ORDER", seq_num)
        book.delete_order(order_id)
        self._log_bbo(book, seq_num)

    def process_trade(self, seq_num: int, order_id: int, qty: int, price: int) -> None:
        book = self._find_book(order_id, "TRADE", seq_num)
        book.trade_order(order_id, qty, price)
        self._log_bbo(book, seq_num)

    def process_modify_order(
        self, seq_num: int, order_id: int, side: SIDE, qty: int, price: int
    ) -> None:
        book = self._find_book(order_id, "MODIFY_ORDER", seq_num)
        book.modify_order(order_id, side, qty, price)
        self._log_bbo(book, seq_num)

    def process_trade_summary(
        self,
        seq_num: int,
        symbol: int,
        aggressor: SIDE,
        total_qty: int,
        last_price: int,
    ) -> None:
        log.debug(
            f"seq={seq_num}: TRADE Summary symbol={symbol}"
            f" aggressor={'BUY' if aggressor == SIDE.BUY else 'SELL'} "
            f"total_qty={total_qty} last_price={last_price}"
        )

    def _find_book(self, order_id: int, msg: str, seq_num: int) -> OrderBook:
        for book in self.books.values():
            if order_id in book.orders:
                return book

        raise KeyError(
            f"seq={seq_num}: {msg} references order_id={order_id}\n"
            f"This is not in the book. INCONSISTENT STATE"
        )

    def _log_bbo(self, book: OrderBook, seq_num: int) -> None:
        best_bid = book.get_best_bid()
        best_ask = book.get_best_ask()
        record = BBORecord(
            seq_num=seq_num,
            symbol=book.symbol,
            best_bid_price=best_bid[0] if best_bid else None,
            best_bid_qty=best_bid[1] if best_bid else None,
            best_ask_price=best_ask[0] if best_ask else None,
            best_ask_qty=best_ask[1] if best_ask else None,
        )
        self.bbo_by_seq[seq_num] = record
        log.info(
            f"seq={seq_num} sym={book.symbol}: BID={best_bid[1] if best_bid else '-'}@{best_bid[0] if best_bid else '-'} "
            f"ASK={best_ask[1] if best_ask else '-'}@{best_ask[0] if best_ask else '-'}"
            f" volume={book.total_volume}"
        )


class SequenceTracker:
    __slots__ = "expected_seq"

    def __init__(self):
        self.expected_seq: Optional[int] = None

    def check(self, seq_num: int) -> None:
        if self.expected_seq is None:
            self.expected_seq = seq_num + 1
            return
        if seq_num != self.expected_seq:
            raise ValueError(
                f"Sequence Gap: expected seq={self.expected_seq}, got seq={seq_num}. NEED TO RESYNC"
            )

        self.expected_seq = seq_num + 1


class SnapShotSynchronizer:
    __slots__ = (
        "book_manager",
        "seq_tracker",
        "sync",
        "last_snap_seq_num",
        "live_buffer",
        "snap_state",
        "snap_complete",
        "completed_symbols",
    )

    def __init__(self, manager: OrderBookManager, seq_tracker: SequenceTracker) -> None:
        self.book_manager: OrderBookManager = manager
        self.seq_tracker: SequenceTracker = seq_tracker
        self.sync: bool = False
        self.last_snap_seq_num: int = 0
        self.live_buffer: List[Tuple[MDHeader, trade_body]] = []
        self.snap_state: Dict[int, Dict[str, int]] = {}
        self.snap_complete: bool = False
        self.completed_symbols: set[int] = set()

    def handle_snapshot_message(self, header: MDHeader, body: trade_body) -> None:
        if header.msg_type == MSG_TYPE.SNAPSHOT_INFO and isinstance(body, SnapshotInfo):
            self._handle_snapshot_info(body)

        elif header.msg_type == MSG_TYPE.NEW_ORDER and isinstance(body, NewOrder):
            self._handle_snapshot_order(header, body)
        else:
            log.warning(
                f"SNAP: Unexpected msg_type={header.msg_type} on snapshot channel"
            )

    def buffer_live_message(self, header: MDHeader, body: trade_body) -> None:
        self.live_buffer.append((header, body))

    def replay_buffered_messages(self) -> None:
        if not self.live_buffer:
            log.warning("SNAP: replay called with empty live buffer")
            self.sync = True
            return

        if self.live_buffer[0][0].seq_num > self.last_snap_seq_num:
            raise ValueError(
                f"SNAP: last snapshot seq_num read in is not greater than first live buffer seq_num"
            )

        self.seq_tracker.expected_seq = self.last_snap_seq_num + 1
        replayed: int = 0
        skipped: int = 0

        log.info(f"SNAPSHOT SEQ: {self.last_snap_seq_num}")
        for header, body in self.live_buffer:
            if header.seq_num > self.last_snap_seq_num:
                self.seq_tracker.check(header.seq_num)
                dispatch_live_message(header, body, self.book_manager)
                replayed += 1
            else:
                skipped = 0
        log.info(
            f"Replay complete: {replayed} messages replayed, "
            f"{skipped} skipped (seq <= {self.last_snap_seq_num})"
        )
        self.live_buffer.clear()
        self.sync = True

    def _handle_snapshot_info(self, body: SnapshotInfo) -> None:
        symbol = body.symbol
        last_md_seq_num = body.last_md_seq_num

        if (
            self.live_buffer
            and self.live_buffer[0][0].seq_num < self.last_snap_seq_num
            and symbol in self.completed_symbols
        ):
            self.snap_complete = True
            return

        if symbol in self.completed_symbols:
            self.completed_symbols.remove(symbol)

        bid_count = body.bid_count
        ask_count = body.ask_count

        self.snap_state[symbol] = {
            "ask_count": ask_count,
            "bid_count": bid_count,
            "last_md_seq_num": last_md_seq_num,
            "orders_received": 0,
            "expected_total": ask_count + bid_count,
        }

        self.last_snap_seq_num = max(self.last_snap_seq_num, last_md_seq_num)

        book = self.book_manager.get_or_create_book(symbol)
        book.clear()
        log.info("SNAP: %s — expecting %d orders", body, ask_count + bid_count)

    def _handle_snapshot_order(self, header: MDHeader, body: NewOrder) -> None:
        symbol = body.symbol
        if symbol not in self.snap_state:
            log.warning(
                f"SNAP: NEW_ORDER for symbol={symbol} without preceding SNAPSHOT_INFO. Ignoring."
            )
            return

        if symbol in self.completed_symbols:
            raise ValueError(f"LOGIC is messed up")

        book = self.book_manager.get_or_create_book(symbol)
        book.add_order(
            order_id=body.order_id,
            symbol=symbol,
            side=body.side,
            qty=body.quantity,
            price=body.price,
            timestamp=header.timestamp,
        )

        self.snap_state[symbol]["orders_received"] += 1
        state = self.snap_state[symbol]
        log.info(
            f"SNAP: symbol={symbol} count={state['orders_received']}/{state['expected_total']} \n{body}"
        )

        if state["orders_received"] == state["expected_total"]:
            log.info(
                f"SNAP: Symbol {symbol} snapshot complete. Received {state['orders_received']} orders (bids={state['bid_count']}, asks={state['ask_count']})"
            )
            self.completed_symbols.add(symbol)
            book.validate()


def dispatch_live_message(
    header: MDHeader, body: trade_body, manager: OrderBookManager
) -> None:
    if header.msg_type == MSG_TYPE.NEW_ORDER and isinstance(body, NewOrder):
        manager.process_new_order(
            seq_num=header.seq_num,
            timestamp=header.timestamp,
            order_id=body.order_id,
            symbol=body.symbol,
            side=body.side,
            qty=body.quantity,
            price=body.price,
            flags=body.flags,
        )
    elif header.msg_type == MSG_TYPE.DELETE_ORDER and isinstance(body, DeleteOrder):
        manager.process_delete_order(seq_num=header.seq_num, order_id=body.order_id)
    elif header.msg_type == MSG_TYPE.MODIFY_ORDER and isinstance(body, ModifyOrder):
        manager.process_modify_order(
            seq_num=header.seq_num,
            order_id=body.order_id,
            side=body.side,
            qty=body.quantity,
            price=body.price,
        )
    elif header.msg_type == MSG_TYPE.TRADE and isinstance(body, Trade):
        manager.process_trade(
            seq_num=header.seq_num,
            order_id=body.order_id,
            qty=body.quantity,
            price=body.price,
        )
    elif header.msg_type == MSG_TYPE.TRADE_SUMMARY and isinstance(body, TradeSummary):
        manager.process_trade_summary(
            seq_num=header.seq_num,
            symbol=body.symbol,
            aggressor=body.aggressor_side,
            total_qty=body.total_quantity,
            last_price=body.last_price,
        )
    elif header.msg_type == MSG_TYPE.SNAPSHOT_INFO and isinstance(body, SnapshotInfo):
        raise KeyError(
            f"seq={header.seq_num}: SNAPSHOT_INFO (type 6) received on LIVE channel! "
            f"This should NEVER happen. Check channel routing."
        )
    elif header.msg_type == MSG_TYPE.HEARTBEAT:
        log.info(f"seq={header.seq_num}: HEARTBEAT")
    else:
        log.warning("seq=%d: unknown msg_type=%s", header.seq_num, header.msg_type)
