import importlib.util
import unittest

HAVE = all(importlib.util.find_spec(m) for m in ('numpy', 'scipy'))


@unittest.skipUnless(HAVE, 'numpy/scipy not installed')
class PlacementTests(unittest.TestCase):
    def test_short_span_gets_no_boundaries(self):
        import numpy as np
        import boundaries_v2b as v
        self.assertEqual(v.predict(np.zeros(600), 0, 200), [])

    def test_strong_peak_splits_a_span(self):
        import numpy as np
        import boundaries_v2b as v
        p = np.zeros(600); p[300] = 0.9
        self.assertEqual([b['start_seconds'] for b in v.predict(p, 0, 600)], [300])

    def test_curve_round_trip(self):
        import numpy as np
        import boundaries_v2b as v
        p = np.linspace(0, 1, 50)
        self.assertLess(float(abs(v.decode_curve(v.encode_curve(p)) - p).max()), 0.003)


if __name__ == '__main__':
    unittest.main()
