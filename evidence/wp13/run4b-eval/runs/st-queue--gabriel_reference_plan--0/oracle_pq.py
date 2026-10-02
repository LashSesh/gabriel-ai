import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from pq import PriorityQueue


class OracleTests(unittest.TestCase):
    def test_fifo_among_equal_priorities(self):
        queue = PriorityQueue()
        queue.push(1, "z")
        queue.push(1, "a")
        self.assertEqual([queue.pop(), queue.pop()], ["z", "a"])

    def test_items_need_not_be_comparable(self):
        queue = PriorityQueue()
        queue.push(1, {"id": 2})
        queue.push(1, {"id": 1})
        self.assertEqual(queue.pop(), {"id": 2})


if __name__ == "__main__":
    unittest.main()
