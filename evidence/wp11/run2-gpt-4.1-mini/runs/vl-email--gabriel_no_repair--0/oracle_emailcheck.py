import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from emailcheck import is_valid_email


class OracleTests(unittest.TestCase):
    def test_domain_needs_dot(self):
        self.assertFalse(is_valid_email("a@b"))
        self.assertFalse(is_valid_email("a@b."))
        self.assertFalse(is_valid_email("a@.b"))

    def test_dotted_domain_is_valid(self):
        self.assertTrue(is_valid_email("a@b.co"))

    def test_basic_still_works(self):
        self.assertTrue(is_valid_email("user@example.com"))
        self.assertFalse(is_valid_email("no-at-sign"))


if __name__ == "__main__":
    unittest.main()
