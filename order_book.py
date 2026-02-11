#!/usr/bin/env python3

import heapq
from typing import Dict, Optional, Tuple, List
from market_data_struct import *
from dataclasses import dataclass

class OrderBook:

    def __init__(self, symbol: int):
        self.symbol: int = symbol
        self.bid_heap: List[int] = []
        self.bid_levels: dict[int, PriceLevel] = {}
        self.ask_heap: List[int] = []
        self.ask_levels: dict[int, PriceLevel] = {}
        self.orders: dict[int, Order] = {}

    def add_order(self, order_id: int, symbol: int, side: SIDE, qty: int, price: int, timestamp: int) -> None:
        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=qty,
            price=price,
            timestamp=timestamp
        )
        if order_id in self.orders:
            raise ValueError(f"[Book {symbol}] Duplicate order id: {id}")

        # TODO: turn all print to raise ValueError
        if qty <= 0:
            print(f"[Book {symbol}] qty={qty} qty <=0 for order id: {id}")
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
        #TODO: turn all prints to `raise KeyError`
        if level.total_qty < 0:
            print(f"[Book {self.symbol}] Negative total quantity={level.total_qty}"
                             f"price={order.price} after deleting order id {order_id}")
        if level.order_count < 0:
            print(f"[Book {self.symbol}] Negative order_count={level.order_count}"
                             f"price={order.price} after deleting order id {order_id}")
        if level.order_count == 0:
            if level.total_qty != 0:
                print(f"[Book {self.symbol}] order_count=0 but total_qty{level.total_qty}"
                                 f"at price={order.price}. INCONSISTENT STATE")
            del levels[order.price]

    def trade_order(self, order_id: int, qty: int, price: int) -> None:
        #TODO -> convert print -> to RAISE KeyError and do error check here
        if order_id not in self.orders:
            return
        order = self.orders[order_id]
        if order.side == SIDE.BUY:
            levels = self.bid_levels
        else:
            levels = self.ask_levels

        level = levels[order.price]

        order.quantity -= qty
        level.total_qty -= qty

        if level.total_qty < 0:
            print(f"[Book {self.symbol}] Negative total quantity={level.total_qty}"
                  f"\nprice={order.price} after trading worder id {order_id}")

        if order.quantity == 0:
            del self.orders[order_id]
            level.order_count -= 1

            if level.order_count < 0:
                print(f"[Book {self.symbol}] Negative order_count={level.order_count}"
                      f"price={order.price} after trading order id {order_id}")

            if level.order_count == 0:
                if level.total_qty != 0:
                    print(f"[Book {self.symbol}] order_count=0 but total_qty{level.total_qty}"
                                     f"at price={order.price}. INCONSISTENT STATE")
                del levels[order.price]

    def modify_order(self, order_id: int, side: SIDE, qty: int, price: int) -> None:
        # TODO -> error checking
        if order_id not in self.orders:
            return

        order = self.orders[order_id]
        symbol = order.symbol
        old_time = order.timestamp

        self.delete_order(order_id)
        self.add_order(order_id=order_id,
                       symbol=symbol,
                       side=side,
                       qty=qty,
                       price=price,
                       timestamp=old_time)

    def get_best_bid(self) -> Optional[Tuple[int, int]]:
        self._clear_top_of_bid()
        if not self.bid_heap:
            return None
        best_price = -self.bid_heap[0]
        level = self.bid_levels[best_price]
        return (best_price, level.total_qty)

    def get_best_ask(self) -> Optional[Tuple[int, int]]:
        self._clear_top_of_ask()
        if not self.ask_heap:
            return None
        best_price = self.ask_heap[0]
        level = self.ask_levels[best_price]
        return (best_price, level.total_qty)

    def validate(self):
        """add validation"""
        pass

    def clear(self):
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
        lines = [f"OrderBook(symbol={self.symbol})"]
        lines.append("=" * 60)


        # Bid Heap
        lines.append(f"Bid Heap (negated, len={len(self.bid_heap)}):")
        lines.append(f"  {self.bid_heap}")

        # Bid Levels
        lines.append(f"Bid Levels (dict, len={len(self.bid_levels)}):")
        for price in sorted(self.bid_levels.keys(), reverse=True):
            level = self.bid_levels[price]
            lines.append(f"  {price}: qty={level.total_qty}, orders={level.order_count}")

        lines.append("-" * 60)

        # Ask Heap
        lines.append(f"Ask Heap (len={len(self.ask_heap)}):")
        lines.append(f"  {self.ask_heap}")

        # Ask Levels
        lines.append(f"Ask Levels (dict, len={len(self.ask_levels)}):")
        for price in sorted(self.ask_levels.keys()):
            level = self.ask_levels[price]
            lines.append(f"  {price}: qty={level.total_qty}, orders={level.order_count}")

        lines.append("-" * 60)

        # Orders
        lines.append(f"Orders (dict, len={len(self.orders)}):")
        for order_id, order in sorted(self.orders.items()):
            lines.append(f"  {order}")

        return "\n".join(lines)

class OrderBookManager:

    def __init__(self):
        self.books: Dict[int, OrderBook] = {}
        self.bbo_log: List[BBORecord] = []
        self.bbo_by_seq: Dict[int, BBORecord] = {}
        self._total_volume: int = 0
        self.cumulative_volume: Dict[int, int] = {}

    def get_or_create_book(self, symbol: int) -> OrderBook:
        if symbol not in self.books:
            self.books[symbol] = OrderBook(symbol=symbol)
            print(f"{symbol} added to book")
        return self.books[symbol]

    def process_new_order(self, seq_num: int, timestamp: int, order_id: int, symbol: int, side: SIDE, qty: int, price: int, flags: int) -> None:
        # TODO: flags may be used later on
        book = self.get_or_create_book(symbol)
        book.add_order(order_id, symbol, side, qty, price, timestamp)
        self._record_volume(seq_num)
        self._log_bbo(book, seq_num)

    def process_delete_order(self, seq_num: int, order_id: int) -> None:
        book = self._find_book(order_id, "DELETE_ORDER", seq_num)
        if not book:
            print('need to sync')
            return
        book.delete_order(order_id)
        self._record_volume(seq_num)
        self._log_bbo(book, seq_num)

    def process_trade(self, seq_num: int, order_id: int, qty: int, price: int) -> None:
        book = self._find_book(order_id, "TRADE", seq_num)
        if not book:
            print('need to sync')
            return
        book.trade_order(order_id, qty, price)
        self._record_volume(seq_num)
        self._log_bbo(book, seq_num)

    def process_modify_order(self, seq_num: int, order_id: int, side: SIDE, qty: int, price: int) -> None:
        book = self._find_book(order_id, "MODIFY_ORDER", seq_num)
        if not book:
            print('need to sync')
            return
        book.modify_order(order_id, side, qty, price)
        self._record_volume(seq_num)
        self._log_bbo(book, seq_num)

    def process_trade_summary(self, seq_num: int, symbol: int, aggressor: SIDE, total_qty: int, last_price: int) -> None:
        # TODO: ASK about trade summary
        self._record_volume(seq_num)
        print(f"seq={seq_num}: TRADE Summary symbol={symbol}"
              f" aggressor={'BUY' if aggressor == SIDE.BUY else 'SELL'} "
              f"total_qty={total_qty} last_price={last_price}")

    def process_heartbeat(self, seq_num: int) -> None:
        self._record_volume(seq_num)

    def get_volume_in_range(self, seq_start: int, seq_end: int) -> int:
        vol_end = self.cumulative_volume[seq_end]
        vol_start = self.cumulative_volume[seq_start]
        return vol_end - vol_start

    def _find_book(self, order_id: int, msg: str, seq_num: int) -> OrderBook:
        for symbol, book in self.books.items():
            if order_id in book.orders:
                return book

        #raise KeyError(
        print(
            f"seq={seq_num}: {msg} references order_id={order_id}\n"
            f"This is not in the book. INCONSISTENT STATE"
        )
        return None

    def _record_volume(self, seq_num: int) -> None:
        self.cumulative_volume[seq_num] = self._total_volume

    def _log_bbo(self, book: OrderBook, seq_num: int) -> None:
        best_bid = book.get_best_bid()
        best_ask = book.get_best_ask()
        record = BBORecord(
            seq_num = seq_num,
            symbol = book.symbol,
            best_bid_price = best_bid[0] if best_bid else None,
            best_bid_qty = best_bid[1] if best_bid else None,
            best_ask_price = best_ask[0] if best_ask else None,
            best_ask_qty = best_ask[1] if best_ask else None
        )
        self.bbo_log.append(record)
        self.bbo_by_seq[seq_num] = record
        print(f"seq={seq_num} sym={book.symbol}: BID={best_bid[0] if best_bid else '-'}x{best_bid[1] if best_bid else '-'} "
              f"ASK={best_ask[0] if best_ask else '-'}x{best_ask[1] if best_ask else '-'}"
        )



class SnapShotSynchronizer:
    def __init__(self, manager: OrderBookManager):
        self.book_manager = manager
        self.sync: bool = False
        self.last_snap_seq_num: int = 0
        self.live_buffer: List[Tuple[MDHeader, any]] = []
        self.snap_state: Dict[int, any] = {}
        self.snap_complete: bool = False
        self.last_wanted_seq_num: int = 187_900_000

    def handle_snapshot_message(self, header: MDHeader, body: any) -> None:
        # TODO do more error checking -> just trying to get it to run
        if header.msg_type == MSG_TYPE.SNAPSHOT_INFO:
            symbol = body.symbol
            last_md_seq_num = body.last_md_seq_num

            if symbol in self.snap_state and self.snap_state[symbol]["orders_received"] == self.snap_state[symbol]["expected_orders"]:

                if last_md_seq_num < self.last_wanted_seq_num:
                    self.snap_complete = True
                    return

            bid_count = body.bid_count
            ask_count = body.ask_count

            self.snap_state[symbol] = {
                "ask_count": ask_count,
                "bid_count": bid_count,
                "last_md_seq_num": last_md_seq_num,
                "orders_received": 0,
                "expected_orders": ask_count + bid_count
            }

            self.last_snap_seq_num = max(self.last_snap_seq_num, last_md_seq_num)

            #book = self.book_manager.get_or_create_book(symbol)
            #book.clear()
        elif header.msg_type == MSG_TYPE.NEW_ORDER:
            symbol = body.symbol
            if symbol not in self.snap_state:
                print(f"NEW_ORDER for symbol {symbol} wihtout SNAPSHOT INFO")
                return
            self.book_manager.process_new_order(
                seq_num=header.seq_num,
                timestamp=header.timestamp,
                order_id=body.order_id,
                symbol=symbol,
                side=body.side,
                qty=body.quantity,
                price=body.price,
                flags=body.flags
            )
            self.snap_state[symbol]["orders_received"] += 1

            # TODO: add some validation -> ensure book is consistent + log snap finished


        else:
            print(body)
            print("deal with this edge case \n\n\n\n")


    def buffer_live_message(self, header: MDHeader, body: any) -> None:
        self.live_buffer.append((header, body))

    def replay_buffered_messages(self) -> None:
        # TODO add more logging skipped + processed
        for header, body in self.live_buffer:
            if header.seq_num > self.last_snap_seq_num:
                parse_live_message(header, body, self.book_manager)
        self.live_buffer.clear()
        self.sync = True


class SequenceTracker():
    def __init__(self):
        self.expected_seq: Optional[int] = None

    def check(self, seq_num: int) -> None:
        if self.expected_seq is None:
            self.expected_seq = seq_num + 1
            return
        if seq_num != self.expected_seq:
            raise KeyError(f"Sequence Gap: expected seq={self.expected_seq}, got seq={seq_num}. NEED TO RESYNC")

        self.expected_seq = seq_num + 1


def parse_live_message(header: MDHeader, body: any, manager: OrderBookManager) -> None:
    if header.msg_type == MSG_TYPE.NEW_ORDER:
        manager.process_new_order(
            seq_num=header.seq_num,
            timestamp=header.timestamp,
            order_id=body.order_id,
            symbol=body.symbol,
            side=body.side,
            qty=body.quantity,
            price=body.price,
            flags=body.flags
        )
    elif header.msg_type == MSG_TYPE.DELETE_ORDER:
        manager.process_delete_order(
            seq_num=header.seq_num,
            order_id=body.order_id
        )
    elif header.msg_type == MSG_TYPE.MODIFY_ORDER:
        manager.process_modify_order(
            seq_num=header.seq_num,
            order_id=body.order_id,
            side=body.side,
            qty=body.quantity,
            price=body.price
        )
    elif header.msg_type == MSG_TYPE.TRADE:
        manager.process_trade(
            seq_num=header.seq_num,
            order_id=body.order_id,
            qty=body.quantity,
            price=body.price
        )
    elif header.msg_type == MSG_TYPE.TRADE_SUMMARY:
        manager.process_trade_summary(
            seq_num=header.seq_num,
            symbol=body.symbol,
            aggressor=body.aggressor_side,
            total_qty=body.total_quantity,
            last_price=body.last_price
        )
    elif header.msg_type == MSG_TYPE.SNAPSHOT_INFO:
        print("This should not print or be here header.msg_type -> snpashotinfo in parse_message")
    elif header.msg_type == MSG_TYPE.HEARTBEAT:
        manager.process_heartbeat(seq_num=header.seq_num)


