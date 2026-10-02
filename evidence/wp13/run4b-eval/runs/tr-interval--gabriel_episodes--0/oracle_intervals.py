import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from intervals import overlaps


class OracleTests(unittest.TestCase):
    def test_touching_is_not_overlap_in_either_order(self):
        self.assertFalse(overlaps((0, 5), (5, 8)))
        self.assertFalse(overlaps((5, 8), (0, 5)))

    def test_still_overlaps(self):
        self.assertTrue(overlaps((0, 5), (4, 8)))
        self.assertTrue(overlaps((0, 1), (0, 1)))


if __name__ == "__main__":
    unittest.main()
