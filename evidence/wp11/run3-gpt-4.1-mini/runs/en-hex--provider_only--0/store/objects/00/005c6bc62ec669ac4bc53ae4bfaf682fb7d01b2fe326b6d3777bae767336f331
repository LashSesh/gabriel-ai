import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from hexcodec import to_hex, from_hex


class OracleTests(unittest.TestCase):
    def test_small_bytes_padded(self):
        self.assertEqual(to_hex(b"\x00\x0f"), "000f")

    def test_mixed(self):
        self.assertEqual(to_hex(b"\x01\xab"), "01ab")

    def test_round_trip_all_bytes(self):
        data = bytes(range(256))
        self.assertEqual(from_hex(to_hex(data)), data)


if __name__ == "__main__":
    unittest.main()
