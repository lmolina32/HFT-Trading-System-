#!/usr/bin/env python3

import unittest
import sys
import os

# Add parent directory to path to import the modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from order_book import OrderBookManager, SequenceTracker
from market_data_struct import SIDE


class TestOrderBookManager(unittest.TestCase):

    def setUp(self):
        """Set up a fresh OrderBookManager before each test"""
        self.manager = OrderBookManager()

    def test_initialization(self):
        """Test OrderBookManager initializes correctly"""
        self.assertEqual(len(self.manager.books), 0)
        self.assertIsInstance(self.manager.bbo_by_seq, dict)

    def test_get_or_create_book_new_symbol(self):
        """Test creating a new book for a symbol"""
        book = self.manager.get_or_create_book(1)

        self.assertIsNotNone(book)
        self.assertEqual(book.symbol, 1)
        self.assertIn(1, self.manager.books)
        self.assertEqual(len(self.manager.books), 1)

    def test_get_or_create_book_existing_symbol(self):
        """Test getting an existing book"""
        book1 = self.manager.get_or_create_book(1)
        book2 = self.manager.get_or_create_book(1)

        self.assertIs(book1, book2)
        self.assertEqual(len(self.manager.books), 1)

    def test_get_or_create_book_multiple_symbols(self):
        """Test creating books for multiple symbols"""
        book1 = self.manager.get_or_create_book(1)
        book2 = self.manager.get_or_create_book(2)
        book3 = self.manager.get_or_create_book(3)

        self.assertEqual(len(self.manager.books), 3)
        self.assertIn(1, self.manager.books)
        self.assertIn(2, self.manager.books)
        self.assertIn(3, self.manager.books)
        self.assertIsNot(book1, book2)
        self.assertIsNot(book2, book3)

    def test_process_new_order(self):
        """Test processing a new order"""
        self.manager.process_new_order(
            seq_num=1,
            timestamp=1000,
            order_id=100,
            symbol=1,
            side=SIDE.BUY,
            qty=50,
            price=10000,
            flags=0
        )

        self.assertIn(1, self.manager.books)
        book = self.manager.books[1]
        self.assertIn(100, book.orders)
        self.assertEqual(len(book.orders), 1)

    def test_process_new_order_multiple_symbols(self):
        """Test processing new orders for different symbols"""
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_new_order(2, 1001, 200, 2, SIDE.SELL, 30, 10100, 0)

        self.assertEqual(len(self.manager.books), 2)
        self.assertIn(100, self.manager.books[1].orders)
        self.assertIn(200, self.manager.books[2].orders)

    def test_process_new_order_same_symbol(self):
        """Test processing multiple orders for the same symbol"""
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_new_order(2, 1001, 101, 1, SIDE.BUY, 30, 10050, 0)
        self.manager.process_new_order(3, 1002, 102, 1, SIDE.SELL, 40, 10100, 0)

        self.assertEqual(len(self.manager.books), 1)
        book = self.manager.books[1]
        self.assertEqual(len(book.orders), 3)

    def test_process_delete_order(self):
        """Test processing a delete order"""
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_delete_order(2, 100)

        book = self.manager.books[1]
        self.assertNotIn(100, book.orders)

    def test_process_delete_nonexistent_order(self):
        """Test deleting an order that doesn't exist in any book"""
        # Should print 'need to sync' but not crash
        with self.assertRaises(KeyError):
            self.manager.process_delete_order(1, 999)

    def test_process_delete_order_with_multiple_books(self):
        """Test deleting order when multiple books exist"""
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_new_order(2, 1001, 200, 2, SIDE.SELL, 30, 10100, 0)

        self.manager.process_delete_order(3, 100)

        self.assertNotIn(100, self.manager.books[1].orders)
        self.assertIn(200, self.manager.books[2].orders)

    def test_process_trade(self):
        """Test processing a trade"""
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_trade(2, 100, 20, 10000)

        book = self.manager.books[1]
        order = book.orders[100]
        self.assertEqual(order.quantity, 30)

    def test_process_trade_full_fill(self):
        """Test processing a trade that completely fills an order"""
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_trade(2, 100, 50, 10000)

        book = self.manager.books[1]
        self.assertNotIn(100, book.orders)

    def test_process_trade_nonexistent_order(self):
        """Test trading an order that doesn't exist"""
        # Should print 'need to sync' but not crash
        with self.assertRaises(KeyError):
            self.manager.process_trade(1, 999, 50, 10000)

    def test_process_modify_order(self):
        """Test processing a modify order"""
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_modify_order(2, 100, SIDE.BUY, 75, 10050)

        book = self.manager.books[1]
        order = book.orders[100]
        self.assertEqual(order.quantity, 75)
        self.assertEqual(order.price, 10050)

    def test_process_modify_nonexistent_order(self):
        """Test modifying an order that doesn't exist"""
        with self.assertRaises(KeyError):
            self.manager.process_modify_order(1, 999, SIDE.BUY, 50, 10000)

    def test_process_trade_summary(self):
        """Test processing a trade summary message"""
        self.manager.process_trade_summary(
            seq_num=1,
            symbol=1,
            aggressor=SIDE.BUY,
            total_qty=100,
            last_price=10000
        )

    def test_find_book_existing_order(self):
        """Test _find_book with an existing order"""
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)

        book = self.manager._find_book(100, "TEST", 2)

        self.assertIsNotNone(book)
        self.assertEqual(book.symbol, 1)

    def test_find_book_nonexistent_order(self):
        """Test _find_book with a nonexistent order"""
        with self.assertRaises(KeyError):
            self.manager._find_book(999, "TEST", 1)

    def test_find_book_multiple_symbols(self):
        """Test _find_book correctly identifies the right book"""
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)
        self.manager.process_new_order(2, 1001, 200, 2, SIDE.SELL, 30, 10100, 0)
        self.manager.process_new_order(3, 1002, 300, 3, SIDE.BUY, 40, 10200, 0)

        book1 = self.manager._find_book(100, "TEST", 4)
        book2 = self.manager._find_book(200, "TEST", 5)
        book3 = self.manager._find_book(300, "TEST", 6)

        self.assertEqual(book1.symbol, 1)
        self.assertEqual(book2.symbol, 2)
        self.assertEqual(book3.symbol, 3)

    def test_complex_workflow(self):
        """Test a complex workflow with multiple operations"""
        # Add orders for symbol 1
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 100, 10000, 0)
        self.manager.process_new_order(2, 1001, 101, 1, SIDE.BUY, 50, 10050, 0)
        self.manager.process_new_order(3, 1002, 200, 1, SIDE.SELL, 75, 10100, 0)

        # Add orders for symbol 2
        self.manager.process_new_order(4, 1003, 300, 2, SIDE.BUY, 60, 20000, 0)

        # Trade partial on symbol 1
        self.manager.process_trade(5, 100, 40, 10000)

        # Modify order on symbol 1
        self.manager.process_modify_order(6, 101, SIDE.BUY, 80, 10075)

        # Delete order on symbol 1
        self.manager.process_delete_order(7, 200)

        # Trade complete fill on symbol 2
        self.manager.process_trade(8, 300, 60, 20000)

        # Verify final state
        book1 = self.manager.books[1]
        book2 = self.manager.books[2]

        self.assertEqual(len(book1.orders), 2)  # 100 (partial), 101 (modified)
        self.assertEqual(len(book2.orders), 0)  # 300 fully traded

        # Verify quantities
        self.assertEqual(book1.orders[100].quantity, 60)
        self.assertEqual(book1.orders[101].quantity, 80)
        self.assertEqual(book1.orders[101].price, 10075)

    def test_cross_symbol_operations(self):
        """Test operations across multiple symbols"""
        # Create orders on multiple symbols
        for symbol in range(1, 6):
            self.manager.process_new_order(
                symbol, 1000 + symbol, 100 + symbol, symbol,
                SIDE.BUY, 50, 10000, 0
            )

        self.assertEqual(len(self.manager.books), 5)

        # Delete some orders
        self.manager.process_delete_order(10, 101)
        self.manager.process_delete_order(11, 103)

        # Verify
        self.assertNotIn(101, self.manager.books[1].orders)
        self.assertIn(102, self.manager.books[2].orders)
        self.assertNotIn(103, self.manager.books[3].orders)
        self.assertIn(104, self.manager.books[4].orders)


class TestSequenceTracker(unittest.TestCase):

    def setUp(self):
        """Set up a fresh SequenceTracker before each test"""
        self.tracker = SequenceTracker()

    def test_initialization(self):
        """Test SequenceTracker initializes with no expected sequence"""
        self.assertIsNone(self.tracker.expected_seq)

    def test_first_sequence_number(self):
        """Test that first sequence number is accepted"""
        self.tracker.check(100)
        self.assertEqual(self.tracker.expected_seq, 101)

    def test_sequential_numbers(self):
        """Test that sequential numbers are accepted"""
        self.tracker.check(1)
        self.tracker.check(2)
        self.tracker.check(3)
        self.tracker.check(4)

        self.assertEqual(self.tracker.expected_seq, 5)

    def test_sequence_gap_detected(self):
        """Test that a gap in sequence numbers raises KeyError"""
        self.tracker.check(1)
        self.tracker.check(2)

        with self.assertRaises(ValueError) as context:
            self.tracker.check(4)  # Skip 3

        self.assertIn("Sequence Gap", str(context.exception))
        self.assertIn("expected seq=3", str(context.exception))
        self.assertIn("got seq=4", str(context.exception))

    def test_sequence_gap_large(self):
        """Test detection of large sequence gap"""
        self.tracker.check(1)

        with self.assertRaises(ValueError):
            self.tracker.check(100)

    def test_duplicate_sequence_number(self):
        """Test that duplicate sequence number is detected"""
        self.tracker.check(1)

        with self.assertRaises(ValueError):
            self.tracker.check(1)  # Duplicate

    def test_backward_sequence_number(self):
        """Test that backward sequence number is detected"""
        self.tracker.check(5)

        with self.assertRaises(ValueError):
            self.tracker.check(3)  # Going backward

    def test_long_sequence(self):
        """Test tracking a long sequence of numbers"""
        for i in range(1, 1001):
            self.tracker.check(i)

        self.assertEqual(self.tracker.expected_seq, 1001)

    def test_reset_after_gap(self):
        """Test that tracker maintains state after gap detection"""
        self.tracker.check(1)

        with self.assertRaises(ValueError):
            self.tracker.check(3)  # Gap

        # Expected sequence should remain at 2 (not updated due to gap)
        self.assertEqual(self.tracker.expected_seq, 2)


class TestIntegration(unittest.TestCase):
    """Integration tests combining manager and sequence tracker"""

    def setUp(self):
        """Set up manager and tracker"""
        self.manager = OrderBookManager()
        self.tracker = SequenceTracker()

    def test_ordered_message_sequence(self):
        """Test processing ordered sequence of messages"""
        messages = [
            (1, lambda: self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)),
            (2, lambda: self.manager.process_new_order(2, 1001, 101, 1, SIDE.SELL, 30, 10100, 0)),
            (3, lambda: self.manager.process_trade(3, 100, 20, 10000)),
            (4, lambda: self.manager.process_modify_order(4, 101, SIDE.SELL, 40, 10150)),
            (5, lambda: self.manager.process_delete_order(5, 100)),
        ]

        for seq_num, operation in messages:
            self.tracker.check(seq_num)
            operation()

        # Verify final state
        book = self.manager.books[1]
        self.assertEqual(len(book.orders), 1)
        self.assertIn(101, book.orders)

    def test_detect_gap_in_message_sequence(self):
        """Test that sequence gap is detected in message flow"""
        self.tracker.check(1)
        self.manager.process_new_order(1, 1000, 100, 1, SIDE.BUY, 50, 10000, 0)

        self.tracker.check(2)
        self.manager.process_new_order(2, 1001, 101, 1, SIDE.SELL, 30, 10100, 0)

        # Skip sequence 3
        with self.assertRaises(ValueError):
            self.tracker.check(4)


if __name__ == '__main__':
    unittest.main()
