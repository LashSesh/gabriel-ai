import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from roman import to_int


class OracleTests(unittest.TestCase):
    def test_subtractive(self):
        self.assertEqual(to_int("IV"), 4)
        self.assertEqual(to_int("IX"), 9)

    def test_mixed(self):
        self.assertEqual(to_int("MCMXCIV"), 1994)

    def test_additive_still_works(self):
        self.assertEqual(to_int("LVIII"), 58)


if __name__ == "__main__":
    unittest.main()
