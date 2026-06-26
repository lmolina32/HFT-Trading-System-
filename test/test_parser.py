#!/usr/bin/env python3
"""Tests for the parse_message dispatch table."""

import struct
import unittest

import _path_setup  # noqa: F401

from src.market_data_struct import (
    DeleteOrder,
    MAGIC_NUMBER,
    MDHeader,
    ModifyOrder,
    NewOrder,
    SIDE,
    SnapshotInfo,
    Trade,
    TradeSummary,
)
from src.parser import parse_message
from md_packets import (
    delete_order_packet,
    heartbeat_packet,
    modify_order_packet,
    new_order_packet,
    snapshot_info_packet,
    trade_packet,
    trade_summary_packet,
)


class TestParseMessage(unittest.TestCase):
    def test_parses_new_order(self):
        msg = parse_message(new_order_packet(1, 0, 100, 1, SIDE.BUY, 5, 1000))
        self.assertIsInstance(msg, NewOrder)
        self.assertEqual(msg.order_id, 100)

    def test_parses_delete_order(self):
        msg = parse_message(delete_order_packet(1, 0, 100))
        self.assertIsInstance(msg, DeleteOrder)

    def test_parses_modify_order(self):
        msg = parse_message(modify_order_packet(1, 0, 100, SIDE.BUY, 5, 1000))
        self.assertIsInstance(msg, ModifyOrder)

    def test_parses_trade(self):
        msg = parse_message(trade_packet(1, 0, 100, 5, 1000))
        self.assertIsInstance(msg, Trade)

    def test_parses_trade_summary(self):
        msg = parse_message(trade_summary_packet(1, 0, 1, SIDE.BUY, 10, 100))
        self.assertIsInstance(msg, TradeSummary)

    def test_parses_snapshot_info(self):
        msg = parse_message(snapshot_info_packet(1, 0, 1, 0, 0, 0))
        self.assertIsInstance(msg, SnapshotInfo)

    def test_parses_heartbeat_as_header(self):
        msg = parse_message(heartbeat_packet(1, 0))
        self.assertIsInstance(msg, MDHeader)

    def test_short_packet_raises(self):
        with self.assertRaises(ValueError):
            parse_message(b"\x00" * 10)

    def test_unknown_msg_type_raises(self):
        # Build a header whose msg_type byte is unused (99)
        header = struct.pack("<QHIQB", MAGIC_NUMBER, 23, 1, 0, 99)
        with self.assertRaises(ValueError):
            parse_message(header)


if __name__ == "__main__":
    unittest.main()
