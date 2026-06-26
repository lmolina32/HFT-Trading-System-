#!/usr/bin/env python3
"""Unit tests for safety trackers: position, exposure, PnL, risk."""

import time
import unittest

import _path_setup  # noqa: F401

from src.order_entry_protocol import Side
from src.safety import ExposureTracker, PnLTracker, PositionTracker, RiskTracker


# open_orders schema: order_id -> (symbol, side, qty, price, filled)
def order(symbol, side, qty, price=100, filled=0):
    return (symbol, side, qty, price, filled)


class TestPositionTracker(unittest.TestCase):
    def setUp(self):
        self.pt = PositionTracker()

    def test_unknown_symbol_is_zero(self):
        self.assertEqual(self.pt.get_position(1), 0)
        self.assertEqual(self.pt.get_net_position(), 0)

    def test_buy_increases_position_and_total_bought(self):
        self.pt.update_position(1, 10, 0)
        self.assertEqual(self.pt.get_position(1), 10)
        self.assertEqual(self.pt.total_bought[1], 10)
        self.assertNotIn(1, self.pt.total_sold)

    def test_sell_decreases_position_and_records_total_sold(self):
        self.pt.update_position(1, 0, 5)
        self.assertEqual(self.pt.get_position(1), -5)
        self.assertEqual(self.pt.total_sold[1], 5)

    def test_buy_then_sell_nets_correctly(self):
        self.pt.update_position(1, 10, 0)
        self.pt.update_position(1, 0, 4)
        self.assertEqual(self.pt.get_position(1), 6)
        self.assertEqual(self.pt.total_bought[1], 10)
        self.assertEqual(self.pt.total_sold[1], 4)

    def test_symbols_independent(self):
        self.pt.update_position(1, 10, 0)
        self.pt.update_position(2, 0, 5)
        self.assertEqual(self.pt.get_position(1), 10)
        self.assertEqual(self.pt.get_position(2), -5)
        self.assertEqual(self.pt.get_net_position(), 5)

    def test_combined_fill_in_single_call(self):
        # Single call carrying both buy and sell legs nets to zero
        self.pt.update_position(1, 5, 5)
        self.assertEqual(self.pt.get_position(1), 0)
        self.assertEqual(self.pt.total_bought[1], 5)
        self.assertEqual(self.pt.total_sold[1], 5)


class TestExposureTracker(unittest.TestCase):
    def setUp(self):
        self.et = ExposureTracker()

    def test_empty_book_is_zero(self):
        self.assertEqual(self.et.buy_exposure(1, {}, 0), 0)
        self.assertEqual(self.et.sell_exposure(1, {}, 0), 0)

    def test_long_position_pushes_buy_exposure(self):
        self.assertEqual(self.et.buy_exposure(1, {}, 10), 10)
        # short position lifts sell exposure
        self.assertEqual(self.et.sell_exposure(1, {}, -10), 10)

    def test_open_buy_orders_add_to_buy_exposure(self):
        oo = {1: order(1, Side.BUY, 20)}
        self.assertEqual(self.et.buy_exposure(1, oo, 0), 20)
        self.assertEqual(self.et.buy_exposure(1, oo, 5), 25)

    def test_open_sell_orders_add_to_sell_exposure(self):
        oo = {1: order(1, Side.SELL, 15)}
        self.assertEqual(self.et.sell_exposure(1, oo, 0), 15)

    def test_filled_quantity_is_excluded_from_exposure(self):
        oo = {1: order(1, Side.BUY, 20, filled=8)}
        self.assertEqual(self.et.buy_exposure(1, oo, 0), 12)

    def test_other_symbols_are_ignored(self):
        oo = {1: order(2, Side.BUY, 50)}
        self.assertEqual(self.et.buy_exposure(1, oo, 0), 0)

    def test_opposite_side_orders_dont_cross(self):
        oo = {1: order(1, Side.SELL, 15)}
        self.assertEqual(self.et.buy_exposure(1, oo, 0), 0)


class TestPnLTracker(unittest.TestCase):
    def setUp(self):
        self.pnl = PnLTracker()

    def test_initial_pnl_is_zero(self):
        self.assertEqual(self.pnl.get_pnl(), 0.0)

    def test_buy_consumes_cash(self):
        self.pnl.on_fill_buy(1, 10, 100)
        self.assertEqual(self.pnl.get_pnl(), -1000.0)

    def test_sell_produces_cash(self):
        self.pnl.on_fill_sell(1, 10, 100)
        self.assertEqual(self.pnl.get_pnl(), 1000.0)

    def test_round_trip_profit(self):
        self.pnl.on_fill_buy(1, 10, 100)
        self.pnl.on_fill_sell(1, 10, 110)
        self.assertEqual(self.pnl.get_pnl(), 100.0)

    def test_round_trip_loss(self):
        self.pnl.on_fill_buy(1, 10, 100)
        self.pnl.on_fill_sell(1, 10, 90)
        self.assertEqual(self.pnl.get_pnl(), -100.0)

    def test_pnl_aggregates_across_symbols(self):
        self.pnl.on_fill_buy(1, 5, 100)   # -500
        self.pnl.on_fill_sell(2, 5, 120)  # +600
        self.assertEqual(self.pnl.get_pnl(), 100.0)


def _make_trackers():
    return RiskTracker(), PositionTracker(), ExposureTracker(), PnLTracker()


def _check(rt, pt, et, pnl, *, symbol=1, side=Side.BUY, qty=1, price=100,
           open_orders=None, seq=1):
    return rt.is_valid(
        symbol, side, qty, price,
        open_orders or {}, pt, et, pnl, seq,
    )


class TestRiskTracker(unittest.TestCase):
    def test_baseline_order_passes(self):
        rt, pt, et, pnl = _make_trackers()
        ok, reason = _check(rt, pt, et, pnl)
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "")

    def test_non_positive_quantity_rejected(self):
        rt, pt, et, pnl = _make_trackers()
        self.assertFalse(_check(rt, pt, et, pnl, qty=0)[0])
        self.assertFalse(_check(rt, pt, et, pnl, qty=-1)[0])

    def test_non_positive_price_rejected(self):
        rt, pt, et, pnl = _make_trackers()
        self.assertFalse(_check(rt, pt, et, pnl, price=0)[0])
        self.assertFalse(_check(rt, pt, et, pnl, price=-1)[0])

    def test_max_qty_per_order(self):
        rt, pt, et, pnl = _make_trackers()
        ok, _ = _check(rt, pt, et, pnl, qty=rt.max_qty_per_order + 1)
        self.assertFalse(ok)

    def test_max_qty_per_side(self):
        rt, pt, et, pnl = _make_trackers()
        # max_qty_per_side (500) is tighter than per-order (1000), so trip this first
        ok, _ = _check(rt, pt, et, pnl, qty=rt.max_qty_per_side + 1)
        self.assertFalse(ok)

    def test_exposure_limit_blocks(self):
        rt, pt, et, pnl = _make_trackers()
        pt.symbol_position[1] = rt.max_exposure
        ok, _ = _check(rt, pt, et, pnl, qty=1)
        self.assertFalse(ok)

    def test_exposure_aware_of_open_orders(self):
        rt, pt, et, pnl = _make_trackers()
        open_orders = {1: order(1, Side.BUY, rt.max_exposure)}
        ok, _ = _check(rt, pt, et, pnl, qty=1, open_orders=open_orders)
        self.assertFalse(ok)

    def test_position_limit_for_buy(self):
        rt, pt, et, pnl = _make_trackers()
        pt.symbol_position[1] = rt.position_limit
        ok, _ = _check(rt, pt, et, pnl, side=Side.BUY, qty=1)
        self.assertFalse(ok)

    def test_position_limit_for_sell(self):
        rt, pt, et, pnl = _make_trackers()
        pt.symbol_position[1] = -rt.position_limit
        ok, _ = _check(rt, pt, et, pnl, side=Side.SELL, qty=1)
        self.assertFalse(ok)

    def test_pnl_floor_kills_new_orders(self):
        rt, pt, et, pnl = _make_trackers()
        pnl.cash = float(rt.min_pnl)  # exactly at floor → kill
        ok, _ = _check(rt, pt, et, pnl)
        self.assertFalse(ok)

    def test_orders_per_second_window(self):
        rt, pt, et, pnl = _make_trackers()
        for _ in range(rt.max_orders_per_second):
            self.assertTrue(_check(rt, pt, et, pnl)[0])
        # next one in same second is rejected
        self.assertFalse(_check(rt, pt, et, pnl)[0])
        # forcing the window forward unblocks
        rt.last_second_time = time.monotonic() - 2.0
        # NB: also bump seq to reset per-seq counter
        self.assertTrue(_check(rt, pt, et, pnl, seq=999)[0])

    def test_unacked_orders_cap(self):
        rt, pt, et, pnl = _make_trackers()
        open_orders = {i: order(1, Side.BUY, 1) for i in range(rt.max_unacked_orders)}
        ok, _ = _check(rt, pt, et, pnl, open_orders=open_orders)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
