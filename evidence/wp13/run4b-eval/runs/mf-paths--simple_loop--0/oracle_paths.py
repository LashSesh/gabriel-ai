import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from paths import normalize
from router import match


class OracleTests(unittest.TestCase):
    def test_trailing_slash_dropped(self):
        self.assertEqual(normalize("/users/"), "/users")
        self.assertEqual(normalize("users///"), "/users")

    def test_root_kept(self):
        self.assertEqual(normalize("/"), "/")

    def test_router_uses_normalize(self):
        self.assertEqual(match("/users/me/"), "profile")


if __name__ == "__main__":
    unittest.main()
