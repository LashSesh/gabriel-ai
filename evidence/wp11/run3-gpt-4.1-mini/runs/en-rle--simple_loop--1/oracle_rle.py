import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from rle import encode, decode


class OracleTests(unittest.TestCase):
    def test_single_character_runs_kept(self):
        self.assertEqual(encode("aaab"), [("a", 3), ("b", 1)])

    def test_all_singletons(self):
        self.assertEqual(encode("abc"), [("a", 1), ("b", 1), ("c", 1)])

    def test_round_trip(self):
        for text in ("hello world", "x", "", "aabbbc"):
            self.assertEqual(decode(encode(text)), text)


if __name__ == "__main__":
    unittest.main()
