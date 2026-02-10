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
            print("\n\n\n\n")
            print(heap)

    def delete_order(self, order_id: int) -> None:
        if order_id not in self.orders:
            return
        order = self.orders.pop(order_id)
        if order.side == SIDE.BUY:
            print('buy')
            levels = self.bid_levels
        else:
            print('ask')
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
        old_time = order.timestamp

        self.delete_order(order_id)
        self.add_order(order_id=order_id,
                       symbol=symbol,
                       side=side,
                       qty=qty,
                       price=price,
                       timestamp=old_time)

    def get_best_bid(self):
        pass

    def get_best_ask(self):
        pass

    def validate(self):
        """add validation"""
        pass

    def clear(self):
        """Error -> clear book"""
        pass

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
        self.bbo_log: List[BBORecord] = {}

    def get_or_create_book(self, symbol: int) -> OrderBook:
        if symbol not in self.books:
            self.books[symbol] = OrderBook(symbol=symbol)
            print(f"{symbol} added to book")
        return self.books[symbol]

    def process_new_order(self, seq_num: int, timestamp: int, order_id: int, symbol: int, side: SIDE, qty: int, price: int, flags: int) -> None:
        # TODO: flags may be used later on
        book = self.get_or_create_book(symbol)
        book.add_order(order_id, symbol, side, qty, price, timestamp)

    def process_delete_order(self, seq_num: int, order_id: int) -> None:
        book = self._find_book(order_id, "DELETE_ORDER", seq_num)
        if not book:
            print('need to sync')
            return
        book.delete_order(order_id)

    def process_trade(self, seq_num: int, order_id: int, qty: int, price: int) -> None:
        book = self._find_book(order_id, "TRADE", seq_num)
        if not book:
            print('need to sync')
            return
        book.trade_order(order_id, qty, price)

    def process_modify_order(self, seq_num: int, order_id: int, side: SIDE, qty: int, price: int) -> None:
        book = self._find_book(order_id, "MODIFY_ORDER", seq_num)
        if not book:
            print('need to sync')
            return
        book.modify_order(order_id, side, qty, price)


    def process_trade_summary(self, seq_num: int, symbol: int, aggressor: SIDE, total_qty: int, last_price: int) -> None:
        # TODO: ASK about trad summary
        print(f"seq={seq_num}: TRADE Summary symbol={symbol}"
              f" aggressor={'BUY' if aggressor == SIDE.BUY else 'SELL'} "
              f"total_qty={total_qty} last_price={last_price}")

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
