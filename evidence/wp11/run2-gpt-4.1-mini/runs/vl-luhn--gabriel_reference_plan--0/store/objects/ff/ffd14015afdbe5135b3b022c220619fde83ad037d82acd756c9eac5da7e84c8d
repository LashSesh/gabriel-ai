import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from luhn import is_valid


class OracleTests(unittest.TestCase):
    def test_even_length_valid(self):
        self.assertTrue(is_valid("4539 1488 0343 6467"))

    def test_even_length_invalid(self):
        self.assertFalse(is_valid("4539 1488 0343 6468"))

    def test_odd_length_still_works(self):
        self.assertTrue(is_valid("79927398713"))
        self.assertFalse(is_valid("79927398710"))


if __name__ == "__main__":
    unittest.main()
