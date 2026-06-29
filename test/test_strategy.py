#!/usr/bin/env python3
"""Tests for strategy helpers and the SpoofDetector signal."""

import time
import unittest

import _path_setup  # noqa: F401

from src.order_entry_protocol import Side
from src.strategy import SpoofDetector, TICK_SIZE, get_tick, round_tick


class TestTickHelpers(unittest.TestCase):
    def test_get_tick_known_symbols(self):
        self.assertEqual(get_tick(1), 10)   # GOLD
        self.assertEqual(get_tick(2), 5)    # BLUE
        self.assertEqual(get_tick(13), 10)  # UNDY

    def test_get_tick_unknown_falls_back(self):
        self.assertEqual(get_tick(9999), 5)

    def test_all_dorm_symbols_use_5_tick(self):
        for sym in range(3, 13):
            self.assertEqual(get_tick(sym), 5)

    def test_round_tick_buy_rounds_down(self):
        self.assertEqual(round_tick(107.0, 10, Side.BUY), 100)
        self.assertEqual(round_tick(100.0, 10, Side.BUY), 100)
        self.assertEqual(round_tick(99.9, 10, Side.BUY), 90)

    def test_round_tick_sell_rounds_up(self):
        self.assertEqual(round_tick(101.0, 10, Side.SELL), 110)
        self.assertEqual(round_tick(110.0, 10, Side.SELL), 110)
        self.assertEqual(round_tick(110.1, 10, Side.SELL), 120)


class TestSpoofDetector(unittest.TestCase):
    def setUp(self):
        self.detector = SpoofDetector()

    def test_small_orders_are_ignored(self):
        for oid in range(10):
            self.detector.on_new_order(oid, 1, Side.BUY, 1)
        self.assertEqual(self.detector._tracked, {})

    def test_large_order_then_quick_cancel_marks_spoof(self):
        # Prime the running-average so a 50-lot stands out
        for oid in range(10):
            self.detector.on_new_order(oid, 1, Side.BUY, 1)
        self.detector.on_new_order(999, 1, Side.BUY, 50)
        self.assertIn(999, self.detector._tracked)
        self.detector.on_cancel(999, 1)
        self.assertGreater(self.detector.bid_spoof_qty(1), 0.0)

    def test_cancel_after_window_does_not_count(self):
        for oid in range(10):
            self.detector.on_new_order(oid, 1, Side.SELL, 1)
        self.detector.on_new_order(999, 1, Side.SELL, 100)
        # Backdate so cancel is "stale"
        self.detector._tracked[999] = (
            time.monotonic() - SpoofDetector.WINDOW_S - 1.0,
            Side.SELL,
            100,
        )
        self.detector.on_cancel(999, 1)
        self.assertEqual(self.detector.ask_spoof_qty(1), 0.0)

    def test_trade_stops_spoof_tracking(self):
        for oid in range(10):
            self.detector.on_new_order(oid, 1, Side.BUY, 1)
        self.detector.on_new_order(999, 1, Side.BUY, 50)
        self.detector.on_trade(999)
        self.assertNotIn(999, self.detector._tracked)
        # Cancel after trade is a no-op for the spoof signal
        self.detector.on_cancel(999, 1)
        self.assertEqual(self.detector.bid_spoof_qty(1), 0.0)

    def test_decay_eventually_drops_pressure(self):
        for oid in range(10):
            self.detector.on_new_order(oid, 1, Side.BUY, 1)
        self.detector.on_new_order(999, 1, Side.BUY, 100)
        self.detector.on_cancel(999, 1)
        starting = self.detector.bid_spoof_qty(1)
        self.assertGreater(starting, 0.0)
        for _ in range(50):
            self.detector.decay(1)
        # Aggressive decay should drive pressure to zero (deleted from dict)
        self.assertEqual(self.detector.bid_spoof_qty(1), 0.0)


class TestTickSizeTable(unittest.TestCase):
    def test_every_traded_symbol_has_tick(self):
        # Strategy iterates symbols 1..12 by default; ETF is sym 13
        for sym in range(1, 14):
            self.assertIn(sym, TICK_SIZE)


if __name__ == "__main__":
    unittest.main()
