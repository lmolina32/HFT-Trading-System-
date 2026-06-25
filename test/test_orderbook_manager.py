#!/usr/bin/env python3
"""Unit tests for OrderBookManager and dispatch_live_message."""

import unittest

import _path_setup  # noqa: F401

from src.market_data_struct import (
    DeleteOrder,
    MDHeader,
    ModifyOrder,
    NewOrder,
    SIDE,
    SnapshotInfo,
    Trade,
    TradeSummary,
)
from src.order_book import OrderBookManager, dispatch_live_message
from md_packets import (
    delete_order_packet,
    modify_order_packet,
    new_order_packet,
    snapshot_info_packet,
    trade_packet,
    trade_summary_packet,
    heartbeat_packet,
)


class TestOrderBookManager(unittest.TestCase):
    def setUp(self):
        self.manager = OrderBookManager()

    def test_initial_state(self):
        self.assertEqual(self.manager.books, {})
        self.assertEqual(self.manager.order_id_to_symbol, {})
        self.assertEqual(self.manager.unknown_delete_count, 0)

    def test_get_or_create_book_idempotent(self):
        b1 = self.manager.get_or_create_book(1)
        b2 = self.manager.get_or_create_book(1)
        self.assertIs(b1, b2)
        self.assertEqual(b1.symbol, 1)

    def test_process_new_order_creates_book_and_registers_id(self):
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.assertIn(1, self.manager.books)
        self.assertEqual(self.manager.order_id_to_symbol[100], 1)
        self.assertIn(100, self.manager.books[1].orders)

    def test_process_delete_order_unwinds_id_mapping(self):
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_delete_order(2, 100)
        self.assertNotIn(100, self.manager.books[1].orders)
        self.assertNotIn(100, self.manager.order_id_to_symbol)

    def test_process_delete_unknown_order_counts_silently(self):
        self.manager.process_delete_order(1, 999)
        self.assertEqual(self.manager.unknown_delete_count, 1)
        self.manager.process_delete_order(2, 1000)
        self.assertEqual(self.manager.unknown_delete_count, 2)

    def test_process_trade_unknown_order_raises(self):
        with self.assertRaises(KeyError):
            self.manager.process_trade(1, 999, 10, 100)

    def test_process_modify_unknown_order_raises(self):
        with self.assertRaises(KeyError):
            self.manager.process_modify_order(1, 999, SIDE.BUY, 10, 100)

    def test_process_modify_updates_level(self):
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_modify_order(2, 100, SIDE.BUY, 75, 10050)
        book = self.manager.books[1]
        self.assertEqual(book.orders[100].quantity, 75)
        self.assertEqual(book.orders[100].price, 10050)

    def test_process_trade_partial_fill_keeps_order(self):
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_trade(2, 100, 20, 10000)
        self.assertEqual(self.manager.books[1].orders[100].quantity, 30)
        self.assertEqual(self.manager.books[1].total_volume, 20)

    def test_process_trade_full_fill_removes_order(self):
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_trade(2, 100, 50, 10000)
        self.assertNotIn(100, self.manager.books[1].orders)

    def test_process_trade_summary_is_noop_for_book(self):
        # trade summary is a feed-level event; it should not touch the book
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_trade_summary(2, 1, SIDE.BUY, 100, 10000)
        self.assertEqual(self.manager.books[1].orders[100].quantity, 50)


class TestDispatchLiveMessage(unittest.TestCase):
    def setUp(self):
        self.manager = OrderBookManager()

    def _send(self, packet: bytes, message_cls):
        header = MDHeader(packet)
        body = message_cls(packet) if message_cls is not MDHeader else header
        dispatch_live_message(header, body, self.manager)

    def test_dispatches_new_order(self):
        self._send(new_order_packet(1, 1000, 100, 1, SIDE.BUY, 50, 10000), NewOrder)
        self.assertIn(100, self.manager.books[1].orders)

    def test_dispatches_delete_order(self):
        self._send(new_order_packet(1, 1000, 100, 1, SIDE.BUY, 50, 10000), NewOrder)
        self._send(delete_order_packet(2, 1100, 100), DeleteOrder)
        self.assertNotIn(100, self.manager.books[1].orders)

    def test_dispatches_modify_order(self):
        self._send(new_order_packet(1, 1000, 100, 1, SIDE.BUY, 50, 10000), NewOrder)
        self._send(modify_order_packet(2, 1100, 100, SIDE.BUY, 80, 10050), ModifyOrder)
        self.assertEqual(self.manager.books[1].orders[100].quantity, 80)
        self.assertEqual(self.manager.books[1].orders[100].price, 10050)

    def test_dispatches_trade(self):
        self._send(new_order_packet(1, 1000, 100, 1, SIDE.BUY, 50, 10000), NewOrder)
        self._send(trade_packet(2, 1100, 100, 30, 10000), Trade)
        self.assertEqual(self.manager.books[1].orders[100].quantity, 20)
        self.assertEqual(self.manager.books[1].total_volume, 30)

    def test_trade_summary_is_pure_observer(self):
        self._send(
            trade_summary_packet(1, 1000, 1, SIDE.BUY, 5, 10000),
            TradeSummary,
        )
        # No book has been created from a summary alone
        self.assertEqual(self.manager.books, {})

    def test_heartbeat_is_noop(self):
        packet = heartbeat_packet(1, 1000)
        header = MDHeader(packet)
        dispatch_live_message(header, header, self.manager)
        self.assertEqual(self.manager.books, {})

    def test_snapshot_info_on_live_channel_raises(self):
        packet = snapshot_info_packet(1, 1000, 1, 0, 0, 0)
        header = MDHeader(packet)
        body = SnapshotInfo(packet)
        with self.assertRaises(KeyError):
            dispatch_live_message(header, body, self.manager)


if __name__ == "__main__":
    unittest.main()
