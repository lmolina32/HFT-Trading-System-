#!/usr/bin/env python3
"""Unit tests for SequenceTracker (current contract: returns bool, never raises)."""

import unittest

import _path_setup  # noqa: F401

from src.order_book import SequenceTracker


class TestSequenceTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = SequenceTracker()

    def test_initial_expected_is_none(self):
        self.assertIsNone(self.tracker.expected_seq)

    def test_first_seq_is_accepted_and_primes_expected(self):
        self.assertTrue(self.tracker.check(100))
        self.assertEqual(self.tracker.expected_seq, 101)

    def test_sequential_messages_advance_expected(self):
        for n in range(1, 6):
            self.assertTrue(self.tracker.check(n))
        self.assertEqual(self.tracker.expected_seq, 6)

    def test_gap_is_accepted_and_resyncs_expected(self):
        self.tracker.check(1)
        self.assertTrue(self.tracker.check(5))  # gap of 3, still accepted
        self.assertEqual(self.tracker.expected_seq, 6)

    def test_duplicate_is_rejected_but_does_not_rewind(self):
        self.tracker.check(5)
        self.assertFalse(self.tracker.check(5))  # duplicate
        self.assertFalse(self.tracker.check(3))  # backward
        self.assertEqual(self.tracker.expected_seq, 6)

    def test_long_sequence(self):
        for n in range(1, 1001):
            self.assertTrue(self.tracker.check(n))
        self.assertEqual(self.tracker.expected_seq, 1001)


if __name__ == "__main__":
    unittest.main()
