#!/usr/bin/env python3

import unittest
import sys
import os

# Add parent directory to path to import the modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from order_book import OrderBook
from market_data_struct import SIDE


class TestOrderBook(unittest.TestCase):

    def setUp(self):
        """Set up a fresh OrderBook before each test"""
        self.book = OrderBook(symbol=1)

    def test_initialization(self):
        """Test OrderBook initializes correctly"""
        self.assertEqual(self.book.symbol, 1)
        self.assertEqual(len(self.book.bid_heap), 0)
        self.assertEqual(len(self.book.ask_heap), 0)
        self.assertEqual(len(self.book.bid_levels), 0)
        self.assertEqual(len(self.book.ask_levels), 0)
        self.assertEqual(len(self.book.orders), 0)

    def test_add_single_buy_order(self):
        """Test adding a single buy order"""
        self.book.add_order(
            order_id=100,
            symbol=1,
            side=SIDE.BUY,
            qty=50,
            price=10000,
            timestamp=1000
        )

        self.assertEqual(len(self.book.orders), 1)
        self.assertEqual(len(self.book.bid_levels), 1)
        self.assertEqual(len(self.book.bid_heap), 1)
        self.assertIn(100, self.book.orders)
        self.assertIn(10000, self.book.bid_levels)

        level = self.book.bid_levels[10000]
        self.assertEqual(level.total_qty, 50)
        self.assertEqual(level.order_count, 1)

    def test_add_single_sell_order(self):
        """Test adding a single sell order"""
        self.book.add_order(
            order_id=200,
            symbol=1,
            side=SIDE.SELL,
            qty=30,
            price=10100,
            timestamp=2000
        )

        self.assertEqual(len(self.book.orders), 1)
        self.assertEqual(len(self.book.ask_levels), 1)
        self.assertEqual(len(self.book.ask_heap), 1)
        self.assertIn(200, self.book.orders)
        self.assertIn(10100, self.book.ask_levels)

        level = self.book.ask_levels[10100]
        self.assertEqual(level.total_qty, 30)
        self.assertEqual(level.order_count, 1)

    def test_add_multiple_orders_same_price(self):
        """Test adding multiple orders at the same price level"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.add_order(101, 1, SIDE.BUY, 30, 10000, 1001)
        self.book.add_order(102, 1, SIDE.BUY, 20, 10000, 1002)

        self.assertEqual(len(self.book.orders), 3)
        self.assertEqual(len(self.book.bid_levels), 1)
        self.assertEqual(len(self.book.bid_heap), 1)

        level = self.book.bid_levels[10000]
        self.assertEqual(level.total_qty, 100)
        self.assertEqual(level.order_count, 3)

    def test_add_orders_different_prices(self):
        """Test adding orders at different price levels"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.add_order(101, 1, SIDE.BUY, 30, 10050, 1001)
        self.book.add_order(102, 1, SIDE.BUY, 20, 9950, 1002)

        self.assertEqual(len(self.book.orders), 3)
        self.assertEqual(len(self.book.bid_levels), 3)
        self.assertEqual(len(self.book.bid_heap), 3)

        self.assertIn(10000, self.book.bid_levels)
        self.assertIn(10050, self.book.bid_levels)
        self.assertIn(9950, self.book.bid_levels)

    def test_add_duplicate_order_id(self):
        """Test that adding duplicate order_id raises ValueError"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)

        with self.assertRaises(ValueError):
            self.book.add_order(100, 1, SIDE.BUY, 30, 10050, 1001)

    def test_add_order_zero_quantity(self):
        """Test adding order with zero quantity (should print warning)"""
        # This currently prints but doesn't raise - just verify it adds
        with self.assertRaises(ValueError):
            self.book.add_order(100, 1, SIDE.BUY, 0, 10000, 1000)

    def test_add_order_negative_quantity(self):
        """Test adding order with negative quantity (should print warning)"""
        # This currently prints but doesn't raise - just verify it adds
        with self.assertRaises(ValueError):
            self.book.add_order(100, 1, SIDE.BUY, -10, 10000, 1000)

    def test_delete_existing_order(self):
        """Test deleting an existing order"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.delete_order(100)

        self.assertEqual(len(self.book.orders), 0)
        self.assertEqual(len(self.book.bid_levels), 0)

    def test_delete_nonexistent_order(self):
        """Test deleting an order that doesn't exist"""
        # Should not raise error, just return
        self.book.delete_order(999)
        self.assertEqual(len(self.book.orders), 0)

    def test_delete_order_partial_level(self):
        """Test deleting one order when multiple exist at same price"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.add_order(101, 1, SIDE.BUY, 30, 10000, 1001)

        self.book.delete_order(100)

        self.assertEqual(len(self.book.orders), 1)
        self.assertEqual(len(self.book.bid_levels), 1)

        level = self.book.bid_levels[10000]
        self.assertEqual(level.total_qty, 30)
        self.assertEqual(level.order_count, 1)

    def test_delete_last_order_at_level(self):
        """Test that deleting last order removes the price level"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.delete_order(100)

        self.assertNotIn(10000, self.book.bid_levels)
        self.assertEqual(len(self.book.bid_levels), 0)

    def test_trade_full_order(self):
        """Test trading the full quantity of an order"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.trade_order(100, 50, 10000)

        self.assertNotIn(100, self.book.orders)
        self.assertNotIn(10000, self.book.bid_levels)

    def test_trade_partial_order(self):
        """Test trading partial quantity of an order"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.trade_order(100, 20, 10000)

        self.assertIn(100, self.book.orders)
        order = self.book.orders[100]
        self.assertEqual(order.quantity, 30)

        level = self.book.bid_levels[10000]
        self.assertEqual(level.total_qty, 30)
        self.assertEqual(level.order_count, 1)

    def test_trade_nonexistent_order(self):
        """Test trading an order that doesn't exist"""
        # Should not raise error, just return

        with self.assertRaises(KeyError):
            self.book.trade_order(999, 50, 10000)

    def test_trade_multiple_partials_then_complete(self):
        """Test multiple partial trades followed by complete fill"""
        self.book.add_order(100, 1, SIDE.BUY, 100, 10000, 1000)

        self.book.trade_order(100, 30, 10000)
        self.assertEqual(self.book.orders[100].quantity, 70)

        self.book.trade_order(100, 40, 10000)
        self.assertEqual(self.book.orders[100].quantity, 30)

        self.book.trade_order(100, 30, 10000)
        self.assertNotIn(100, self.book.orders)
        self.assertNotIn(10000, self.book.bid_levels)

    def test_trade_with_multiple_orders_at_level(self):
        """Test trading one order when multiple orders exist at the same level"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.add_order(101, 1, SIDE.BUY, 30, 10000, 1001)

        self.book.trade_order(100, 50, 10000)

        self.assertNotIn(100, self.book.orders)
        self.assertIn(101, self.book.orders)

        level = self.book.bid_levels[10000]
        self.assertEqual(level.total_qty, 30)
        self.assertEqual(level.order_count, 1)

    def test_modify_order_same_price(self):
        """Test modifying order quantity at same price"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.modify_order(100, SIDE.BUY, 75, 10000)

        self.assertIn(100, self.book.orders)
        order = self.book.orders[100]
        self.assertEqual(order.quantity, 75)
        self.assertEqual(order.price, 10000)

        level = self.book.bid_levels[10000]
        self.assertEqual(level.total_qty, 75)

    def test_modify_order_different_price(self):
        """Test modifying order to different price level"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.modify_order(100, SIDE.BUY, 50, 10050)

        self.assertIn(100, self.book.orders)
        order = self.book.orders[100]
        self.assertEqual(order.price, 10050)

        self.assertNotIn(10000, self.book.bid_levels)
        self.assertIn(10050, self.book.bid_levels)

        level = self.book.bid_levels[10050]
        self.assertEqual(level.total_qty, 50)

    def test_modify_order_change_side(self):
        """Test modifying order from BUY to SELL"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.modify_order(100, SIDE.SELL, 50, 10100)

        self.assertIn(100, self.book.orders)
        order = self.book.orders[100]
        self.assertEqual(order.side, SIDE.SELL)

        self.assertEqual(len(self.book.bid_levels), 0)
        self.assertEqual(len(self.book.ask_levels), 1)

    def test_modify_nonexistent_order(self):
        """Test modifying an order that doesn't exist"""

        with self.assertRaises(KeyError):
            self.book.modify_order(999, SIDE.BUY, 50, 10000)

    def test_modify_preserves_timestamp(self):
        """Test that modify preserves original timestamp"""
        original_timestamp = 1000
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, original_timestamp)
        self.book.modify_order(100, SIDE.BUY, 75, 10050)

        order = self.book.orders[100]
        self.assertEqual(order.timestamp, original_timestamp)

    def test_mixed_buy_and_sell_orders(self):
        """Test book with both buy and sell orders"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.add_order(101, 1, SIDE.BUY, 30, 9950, 1001)
        self.book.add_order(200, 1, SIDE.SELL, 40, 10100, 2000)
        self.book.add_order(201, 1, SIDE.SELL, 25, 10150, 2001)

        self.assertEqual(len(self.book.orders), 4)
        self.assertEqual(len(self.book.bid_levels), 2)
        self.assertEqual(len(self.book.ask_levels), 2)
        self.assertEqual(len(self.book.bid_heap), 2)
        self.assertEqual(len(self.book.ask_heap), 2)

    def test_heap_maintains_correct_sign(self):
        """Test that bid heap uses negative prices and ask heap uses positive"""
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.add_order(200, 1, SIDE.SELL, 40, 10100, 2000)

        # Bid heap should contain negative price
        self.assertIn(-10000, self.book.bid_heap)

        # Ask heap should contain positive price
        self.assertIn(10100, self.book.ask_heap)

    def test_complex_sequence_operations(self):
        """Test a complex sequence of add, modify, trade, and delete operations"""
        # Add orders
        self.book.add_order(100, 1, SIDE.BUY, 50, 10000, 1000)
        self.book.add_order(101, 1, SIDE.BUY, 30, 10000, 1001)
        self.book.add_order(200, 1, SIDE.SELL, 40, 10100, 2000)

        # Trade partial
        self.book.trade_order(100, 20, 10000)
        self.assertEqual(self.book.orders[100].quantity, 30)

        # Modify order
        self.book.modify_order(101, SIDE.BUY, 50, 10050)
        self.assertIn(10050, self.book.bid_levels)

        # Delete order
        self.book.delete_order(200)
        self.assertEqual(len(self.book.ask_levels), 0)

        # Trade remaining
        self.book.trade_order(100, 30, 10000)
        self.assertNotIn(100, self.book.orders)

        # Final state check
        self.assertEqual(len(self.book.orders), 1)
        self.assertEqual(len(self.book.bid_levels), 1)


if __name__ == '__main__':
    unittest.main()
