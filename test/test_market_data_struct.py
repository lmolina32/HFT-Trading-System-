#!/usr/bin/env python3
"""Unit tests for parsing of binary market-data messages."""

import unittest

import _path_setup  # noqa: F401

from src.market_data_struct import (
    DeleteOrder,
    MAGIC_NUMBER,
    MDHeader,
    MSG_TYPE,
    MAX_MSG_SIZE,
    ModifyOrder,
    NewOrder,
    SIDE,
    SnapshotInfo,
    SNAPSHOT_MAGIC_NUMBER,
    Trade,
    TradeSummary,
)
from md_packets import (
    delete_order_packet,
    modify_order_packet,
    new_order_packet,
    snapshot_info_packet,
    trade_packet,
    trade_summary_packet,
)


class TestMDHeader(unittest.TestCase):
    def test_parses_all_header_fields(self):
        packet = new_order_packet(seq_num=42, timestamp=12345, order_id=1,
                                  symbol=1, side=SIDE.BUY, quantity=1, price=1)
        header = MDHeader(packet)
        self.assertEqual(header.magic_number, MAGIC_NUMBER)
        self.assertEqual(header.seq_num, 42)
        self.assertEqual(header.timestamp, 12345)
        self.assertEqual(header.msg_type, MSG_TYPE.NEW_ORDER)

    def test_snapshot_magic_is_distinct_from_live(self):
        self.assertNotEqual(SNAPSHOT_MAGIC_NUMBER, MAGIC_NUMBER)

    def test_header_repr_contains_msg_type_name(self):
        packet = new_order_packet(1, 0, 1, 1, SIDE.BUY, 1, 1)
        self.assertIn("NEW_ORDER", repr(MDHeader(packet)))


class TestMessageBodies(unittest.TestCase):
    def test_new_order_parses_all_fields(self):
        packet = new_order_packet(
            seq_num=1, timestamp=0, order_id=42,
            symbol=2, side=SIDE.SELL, quantity=7, price=1234, flags=0,
        )
        msg = NewOrder(packet)
        self.assertEqual(msg.order_id, 42)
        self.assertEqual(msg.symbol, 2)
        self.assertEqual(msg.side, SIDE.SELL)
        self.assertEqual(msg.quantity, 7)
        self.assertEqual(msg.price, 1234)
        self.assertEqual(msg.flags, 0)

    def test_delete_order_parses(self):
        msg = DeleteOrder(delete_order_packet(1, 0, 99))
        self.assertEqual(msg.order_id, 99)

    def test_modify_order_parses(self):
        msg = ModifyOrder(modify_order_packet(1, 0, 100, SIDE.BUY, 5, 9999))
        self.assertEqual(msg.order_id, 100)
        self.assertEqual(msg.side, SIDE.BUY)
        self.assertEqual(msg.quantity, 5)
        self.assertEqual(msg.price, 9999)

    def test_trade_parses(self):
        msg = Trade(trade_packet(1, 0, 100, 25, 555))
        self.assertEqual(msg.order_id, 100)
        self.assertEqual(msg.quantity, 25)
        self.assertEqual(msg.price, 555)

    def test_trade_summary_parses(self):
        msg = TradeSummary(trade_summary_packet(1, 0, 13, SIDE.SELL, 100, 7000))
        self.assertEqual(msg.symbol, 13)
        self.assertEqual(msg.aggressor_side, SIDE.SELL)
        self.assertEqual(msg.total_quantity, 100)
        self.assertEqual(msg.last_price, 7000)

    def test_snapshot_info_parses(self):
        msg = SnapshotInfo(snapshot_info_packet(1, 0, 1, 5, 4, 999))
        self.assertEqual(msg.symbol, 1)
        self.assertEqual(msg.bid_count, 5)
        self.assertEqual(msg.ask_count, 4)
        self.assertEqual(msg.last_md_seq_num, 999)


class TestMaxMessageSize(unittest.TestCase):
    def test_max_message_size_bounds_all_concrete_messages(self):
        # Build one of each and confirm none exceed MAX_MSG_SIZE
        sizes = [
            len(new_order_packet(1, 0, 1, 1, SIDE.BUY, 1, 1)),
            len(delete_order_packet(1, 0, 1)),
            len(modify_order_packet(1, 0, 1, SIDE.BUY, 1, 1)),
            len(trade_packet(1, 0, 1, 1, 1)),
            len(trade_summary_packet(1, 0, 1, SIDE.BUY, 1, 1)),
            len(snapshot_info_packet(1, 0, 1, 0, 0, 0)),
        ]
        for size in sizes:
            self.assertLessEqual(size, MAX_MSG_SIZE)


if __name__ == "__main__":
    unittest.main()
