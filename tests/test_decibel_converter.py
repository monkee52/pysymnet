import math
import unittest

from pysymnet import DecibelConverter


class TestDecibelConverter(unittest.TestCase):
    converter = DecibelConverter()

    def test_from_rcn(self):
        print ("Testing dsp to % conversion -72 to +12")

        print("Testing dsp 0 == -infinity dB")
        db = self.converter.from_rcn(0)

        self.assertAlmostEqual(db, -math.inf, 2)

        print("Testing dsp 65535 == +12 dB")
        db = self.converter.from_rcn(65535)

        self.assertAlmostEqual(db, +12.0, 2)

        print("Testing dsp 1 == -72 dB")
        db = self.converter.from_rcn(1)

        self.assertAlmostEqual(db, -72.0, 2)
    
    def test_to_rcn(self):
        print("Testing dB to dsp conversion -72 to +12")

        print("Testing -infinity dB == dsp 0")
        val = self.converter.to_rcn(-math.inf)

        self.assertEqual(val, 0)

        print("Testing +12 dB == dsp 65535")
        val = self.converter.to_rcn(+12.0)

        self.assertEqual(val, 65535)

        min_db = -71.9977

        print(f"Testing {min_db} dB == dsp 1")

        val = self.converter.to_rcn(min_db)

        self.assertEqual(val, 1)

if __name__ == "__main__":
    unittest.main()
