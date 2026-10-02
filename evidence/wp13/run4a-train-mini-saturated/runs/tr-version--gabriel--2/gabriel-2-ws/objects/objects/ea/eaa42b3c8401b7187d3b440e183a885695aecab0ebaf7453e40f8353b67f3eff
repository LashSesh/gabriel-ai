import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from versions import compare


class OracleTests(unittest.TestCase):
    def test_numeric_components(self):
        self.assertEqual(compare("1.10", "1.9"), 1)
        self.assertEqual(compare("10.0", "9.0"), 1)

    def test_three_components(self):
        self.assertEqual(compare("1.0.1", "1.0"), 1)
        self.assertEqual(compare("1.0", "1.0.0"), 0)


if __name__ == "__main__":
    unittest.main()
