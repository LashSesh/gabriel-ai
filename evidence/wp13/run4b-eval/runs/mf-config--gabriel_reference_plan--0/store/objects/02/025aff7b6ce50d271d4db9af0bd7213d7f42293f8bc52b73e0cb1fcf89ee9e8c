import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from defaults import merge
from config import load


class OracleTests(unittest.TestCase):
    def test_nested_section_keeps_defaults(self):
        self.assertEqual(load({"server": {"port": 9000}})["server"], {"host": "localhost", "port": 9000})

    def test_merge_is_recursive(self):
        self.assertEqual(merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 3}}), {"a": {"x": 1, "y": 3}})
        self.assertEqual(merge({"a": {"b": {"c": 1}}}, {"a": {"b": {"d": 2}}}), {"a": {"b": {"c": 1, "d": 2}}})


if __name__ == "__main__":
    unittest.main()
