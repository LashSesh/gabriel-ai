import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from rot13 import rot13


class OracleTests(unittest.TestCase):
    def test_uppercase_rotated(self):
        self.assertEqual(rot13("Hello, World"), "Uryyb, Jbeyq")

    def test_uppercase_only(self):
        self.assertEqual(rot13("ABCXYZ"), "NOPKLM")

    def test_lowercase_still_works(self):
        self.assertEqual(rot13("uryyb"), "hello")


if __name__ == "__main__":
    unittest.main()
