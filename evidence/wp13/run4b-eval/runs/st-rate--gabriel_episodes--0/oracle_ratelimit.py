import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from ratelimit import Limiter


class OracleTests(unittest.TestCase):
    def test_count_accumulates_while_clock_advances_within_window(self):
        ticks = iter([0, 0, 1, 2])
        limiter = Limiter(2, 10, lambda: next(ticks))
        self.assertTrue(limiter.allow())
        self.assertTrue(limiter.allow())
        self.assertFalse(limiter.allow())

    def test_new_window_resets(self):
        ticks = iter([0, 0, 0, 0, 10, 10, 10])
        limiter = Limiter(2, 10, lambda: next(ticks))
        self.assertEqual([limiter.allow() for _ in range(3)], [True, True, False])
        self.assertEqual([limiter.allow() for _ in range(3)], [True, True, False])


if __name__ == "__main__":
    unittest.main()
