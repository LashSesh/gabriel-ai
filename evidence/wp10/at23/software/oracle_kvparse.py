"""Independent behavioral oracle for the seeded kvparse defect (not part of the repository)."""
import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from kvparse import parse_pairs


class OracleTests(unittest.TestCase):
    def test_empty_string_is_empty_dict(self):
        self.assertEqual(parse_pairs(""), {})

    def test_trailing_comma_is_ignored(self):
        self.assertEqual(parse_pairs("a=1,"), {"a": "1"})

    def test_basic_still_works(self):
        self.assertEqual(parse_pairs("a=1,b=2"), {"a": "1", "b": "2"})


if __name__ == "__main__":
    unittest.main()
