import unittest
from unittest.mock import patch

import discovery_review as dr


class BuildProfileTests(unittest.TestCase):
    def test_profile_text_carries_signals_and_namesakes(self):
        fake = {"profile": "House DJ from Brooklyn.", "aliases": ["Alt"], "home_signals": ["The Lot Radio"],
                "namesakes": ["A singer"]}
        cands = [dr.Candidate("Set at The Lot", "The Lot Radio", 60, 2025, "https://example.com/1")]
        with patch.object(dr, "_run_claude", return_value=dict(fake)) as run:
            out = dr.build_profile("Test DJ", ["Test"], cands, web=False)
        prompt = run.call_args[0][0]
        self.assertNotIn("web search", prompt)
        self.assertIn("Performs as: Test DJ, Test, Alt", out["profile"])
        self.assertIn("The Lot Radio", out["profile"])
        self.assertIn("not this artist): A singer", out["profile"])
        self.assertEqual(out["namesakes"], ["A singer"])

    def test_web_search_only_without_accepted_sets(self):
        fake = {"profile": "p", "aliases": [], "home_signals": [], "namesakes": []}
        with patch.object(dr, "_run_claude", return_value=dict(fake)) as run:
            dr.build_profile("Test DJ", [], [], web=True)
        self.assertEqual(run.call_args[0][3], ("WebSearch",))
        self.assertIn("trust the recordings", run.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
