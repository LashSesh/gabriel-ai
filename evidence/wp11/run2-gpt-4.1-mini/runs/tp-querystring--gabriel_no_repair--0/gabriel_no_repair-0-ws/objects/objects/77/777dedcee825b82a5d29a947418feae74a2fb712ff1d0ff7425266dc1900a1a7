import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from querystring import parse_qs


class OracleTests(unittest.TestCase):
    def test_plus_is_space(self):
        self.assertEqual(parse_qs("q=a+b"), {"q": "a b"})

    def test_key_without_value(self):
        self.assertEqual(parse_qs("flag&a=1"), {"flag": "", "a": "1"})

    def test_percent_still_works(self):
        self.assertEqual(parse_qs("q=a%20b&x=%41"), {"q": "a b", "x": "A"})


if __name__ == "__main__":
    unittest.main()
