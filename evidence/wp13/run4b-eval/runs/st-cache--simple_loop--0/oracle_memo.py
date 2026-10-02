import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from memo import memoize


class OracleTests(unittest.TestCase):
    def test_keyword_arguments_distinguish_and_cache(self):
        calls = []

        @memoize
        def scaled(x, scale=1):
            calls.append((x, scale))
            return x * scale
        self.assertEqual(scaled(2, scale=1), 2)
        self.assertEqual(scaled(2, scale=10), 20)
        self.assertEqual(scaled(2, scale=10), 20)
        self.assertEqual(calls, [(2, 1), (2, 10)])


if __name__ == "__main__":
    unittest.main()
