import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from calendarx import is_leap, days_in_month


class OracleTests(unittest.TestCase):
    def test_century_rule(self):
        self.assertFalse(is_leap(1900))
        self.assertTrue(is_leap(2000))

    def test_february_1900(self):
        self.assertEqual(days_in_month(1900, 2), 28)

    def test_ordinary_leap_still_works(self):
        self.assertTrue(is_leap(2024))


if __name__ == "__main__":
    unittest.main()
