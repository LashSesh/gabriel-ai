import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from stats import median


class OracleTests(unittest.TestCase):
    def test_even_median_is_mean_of_middle(self):
        self.assertEqual(median([4, 1, 3, 2]), 2.5)

    def test_two_values(self):
        self.assertEqual(median([10, 20]), 15.0)

    def test_odd_still_works(self):
        self.assertEqual(median([9, 7, 8]), 8)


if __name__ == "__main__":
    unittest.main()
