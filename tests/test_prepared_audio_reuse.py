import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from worker.jobs import process_set


class PreparedAudioReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.audio = Path(self.tmp.name) / "mix.mp3"
        self.audio.write_bytes(b"prepared audio")
        self.sha = hashlib.sha256(b"prepared audio").hexdigest()
        self.context = SimpleNamespace(audio_file=self.audio, total_segments=12)
        self.row = {"artist_name": "A", "source_metadata": {"mix_info": {"title": "T"}, "segment_count": 12}}

    def tearDown(self):
        self.tmp.cleanup()

    def reuse(self, state, restore=None):
        with mock.patch("worker.pipeline.recognize.restore_set_context",
                        restore or mock.Mock(return_value=self.context)) as patched:
            return process_set._reuse_prepared_audio(self.row, state), patched

    def test_reuses_matching_cached_audio(self):
        result, restore = self.reuse({"audio_sha256": self.sha, "source_url": "https://youtu.be/x"})
        self.assertIs(result, self.context)
        self.assertEqual(restore.call_args.args[0], "https://youtu.be/x")

    def test_mismatched_fingerprint_downloads(self):
        result, _ = self.reuse({"audio_sha256": "0" * 64, "source_url": "u"})
        self.assertIsNone(result)

    def test_missing_cache_downloads(self):
        result, _ = self.reuse({"audio_sha256": self.sha, "source_url": "u"},
                               restore=mock.Mock(side_effect=RuntimeError("Prepared audio file is missing")))
        self.assertIsNone(result)

    def test_first_run_and_legacy_runs_download(self):
        for state in (None, {}, {"audio_sha256": self.sha}):
            result, restore = self.reuse(state)
            self.assertIsNone(result)
            restore.assert_not_called()

    def test_missing_mix_info_downloads(self):
        self.row["source_metadata"] = {}
        result, _ = self.reuse({"audio_sha256": self.sha, "source_url": "u"})
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
