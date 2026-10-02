import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from seqtools import dedupe


class OracleTests(unittest.TestCase):
    def test_order_of_first_occurrence(self):
        self.assertEqual(dedupe([3, 1, 3, 2, 1]), [3, 1, 2])

    def test_strings(self):
        self.assertEqual(dedupe(["b", "a", "b", "c"]), ["b", "a", "c"])

    def test_single(self):
        self.assertEqual(dedupe([7]), [7])


if __name__ == "__main__":
    unittest.main()
