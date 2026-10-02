import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from slug import slugify


class OracleTests(unittest.TestCase):
    def test_collapses_runs(self):
        self.assertEqual(slugify("Hello   World!"), "hello-world")

    def test_strips_edges(self):
        self.assertEqual(slugify(" --x-- "), "x")

    def test_simple_still_works(self):
        self.assertEqual(slugify("Hello World"), "hello-world")


if __name__ == "__main__":
    unittest.main()
