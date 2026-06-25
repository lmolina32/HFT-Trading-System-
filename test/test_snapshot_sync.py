#!/usr/bin/env python3
"""Tests for the snapshot recovery state machine."""

import unittest

import _path_setup  # noqa: F401

from src.market_data_struct import (
    MDHeader,
    NewOrder,
    SIDE,
    SnapshotInfo,
)
from src.order_book import OrderBookManager, SequenceTracker, SnapShotSynchronizer
from md_packets import (
    new_order_packet,
    snapshot_info_packet,
    snapshot_new_order_packet,
)


def _md(packet, cls):
    return MDHeader(packet), cls(packet)


class TestSnapShotSynchronizer(unittest.TestCase):
    def setUp(self):
        self.manager = OrderBookManager()
        self.seq = SequenceTracker()
        self.sync = SnapShotSynchronizer(self.manager, self.seq)
        # Drive total_symbols down so we don't have to build all 13 symbols
        self.sync.total_symbols = 1

    def test_initial_state_is_unsynced(self):
        self.assertFalse(self.sync.sync)
        self.assertFalse(self.sync.snap_complete)
        self.assertEqual(self.sync.live_buffer, [])

    def test_buffered_live_messages_replay_after_snapshot(self):
        # Live data arrives before snapshot — buffer it
        for seq_num in (11, 12, 13):
            header, body = _md(
                new_order_packet(seq_num, 0, 1000 + seq_num, 1, SIDE.BUY, 1, 100),
                NewOrder,
            )
            self.sync.buffer_live_message(header, body)
        self.assertEqual(len(self.sync.live_buffer), 3)

        # Snapshot for symbol 1: 1 bid expected, snapshot seq is 10
        snap_info = snapshot_info_packet(
            1, 0, symbol=1, bid_count=1, ask_count=0, last_md_seq_num=10,
        )
        self.sync.handle_snapshot_message(*_md(snap_info, SnapshotInfo))

        # Deliver the one snapshot order — that completes the symbol; since
        # total_symbols=1 and live_buffer[0].seq_num=11 == snap+1, snap_complete fires.
        order_pkt = snapshot_new_order_packet(2, 0, 500, 1, SIDE.BUY, 1, 99)
        self.sync.handle_snapshot_message(*_md(order_pkt, NewOrder))
        self.assertTrue(self.sync.snap_complete)

        self.sync.replay_buffered_messages()
        self.assertTrue(self.sync.sync)
        # Snapshot order plus 3 buffered live orders all in the book
        self.assertEqual(len(self.manager.books[1].orders), 4)
        # Sequence tracker primed for the next live message
        self.assertEqual(self.seq.expected_seq, 14)

    def test_snapshot_orders_populate_book(self):
        # Declare snapshot with one bid and one ask
        snap_header, snap_body = _md(
            snapshot_info_packet(1, 0, symbol=1, bid_count=1, ask_count=1,
                                 last_md_seq_num=10),
            SnapshotInfo,
        )
        self.sync.handle_snapshot_message(snap_header, snap_body)

        for oid, side, price in [(1, SIDE.BUY, 100), (2, SIDE.SELL, 110)]:
            h, b = _md(
                snapshot_new_order_packet(1, 0, oid, 1, side, 5, price), NewOrder,
            )
            self.sync.handle_snapshot_message(h, b)

        book = self.manager.books[1]
        self.assertIn(1, book.orders)
        self.assertIn(2, book.orders)
        self.assertIn(1, self.sync.completed_symbols)

    def test_snapshot_order_without_info_triggers_resnap(self):
        h, b = _md(
            snapshot_new_order_packet(1, 0, 1, 1, SIDE.BUY, 5, 100), NewOrder,
        )
        self.sync.handle_snapshot_message(h, b)
        # No state should accumulate
        self.assertEqual(self.sync.snap_state, {})

    def test_reset_for_resnap_clears_book_and_state(self):
        snap_header, snap_body = _md(
            snapshot_info_packet(1, 0, 1, 1, 0, 10),
            SnapshotInfo,
        )
        self.sync.handle_snapshot_message(snap_header, snap_body)
        h, b = _md(
            snapshot_new_order_packet(1, 0, 1, 1, SIDE.BUY, 5, 100), NewOrder,
        )
        self.sync.handle_snapshot_message(h, b)

        self.sync._reset_for_resnap()
        self.assertEqual(self.sync.snap_state, {})
        self.assertEqual(self.sync.completed_symbols, set())
        self.assertFalse(self.sync.sync)
        self.assertEqual(self.manager.order_id_to_symbol, {})
        self.assertEqual(self.manager.books[1].orders, {})

    def test_replay_with_empty_buffer_resets(self):
        # Calling replay before any live data forces a re-snap (defensive)
        self.sync.replay_buffered_messages()
        self.assertFalse(self.sync.sync)


if __name__ == "__main__":
    unittest.main()
