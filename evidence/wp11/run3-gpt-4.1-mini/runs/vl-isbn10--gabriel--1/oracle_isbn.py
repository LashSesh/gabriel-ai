import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from isbn import is_valid_isbn10


class OracleTests(unittest.TestCase):
    def test_x_check_digit(self):
        self.assertTrue(is_valid_isbn10("0-8044-2957-X"))

    def test_x_only_in_last_position(self):
        self.assertFalse(is_valid_isbn10("0-X044-2957-1"))

    def test_numeric_still_works(self):
        self.assertTrue(is_valid_isbn10("0-306-40615-2"))
        self.assertFalse(is_valid_isbn10("0-306-40615-3"))


if __name__ == "__main__":
    unittest.main()
