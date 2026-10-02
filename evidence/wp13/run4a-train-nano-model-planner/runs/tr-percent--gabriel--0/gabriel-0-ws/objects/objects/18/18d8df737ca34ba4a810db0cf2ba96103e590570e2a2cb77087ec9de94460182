import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from change import percent_change


class OracleTests(unittest.TestCase):
    def test_zero_baseline_is_undefined(self):
        self.assertIsNone(percent_change(0, 5))
        self.assertIsNone(percent_change(0, 0))

    def test_no_change_is_zero(self):
        self.assertEqual(percent_change(50, 50), 0.0)
        self.assertEqual(percent_change(50, 75), 50.0)


if __name__ == "__main__":
    unittest.main()
