import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from money import round_cents
from ledger import total


class OracleTests(unittest.TestCase):
    def test_halves_away_from_zero(self):
        self.assertEqual(round_cents(0.125), 0.13)
        self.assertEqual(round_cents(2.675), 2.68)
        self.assertEqual(round_cents(-0.125), -0.13)

    def test_total_rounds_each_line(self):
        self.assertEqual(total([0.125, 0.125]), 0.26)

    def test_plain_values_still_work(self):
        self.assertEqual(total([1.10, 2.20]), 3.30)


if __name__ == "__main__":
    unittest.main()
