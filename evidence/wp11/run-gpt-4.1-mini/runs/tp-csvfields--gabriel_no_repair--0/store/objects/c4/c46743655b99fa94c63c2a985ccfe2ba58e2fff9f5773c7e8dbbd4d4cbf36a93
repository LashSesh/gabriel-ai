import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from csvfields import split_fields


class OracleTests(unittest.TestCase):
    def test_doubled_quote_is_unescaped(self):
        self.assertEqual(split_fields('"say ""hi""",b'), ['say "hi"', "b"])

    def test_empty_fields(self):
        self.assertEqual(split_fields("a,,c,"), ["a", "", "c", ""])

    def test_quoted_comma_still_works(self):
        self.assertEqual(split_fields('"x,y",z'), ["x,y", "z"])


if __name__ == "__main__":
    unittest.main()
