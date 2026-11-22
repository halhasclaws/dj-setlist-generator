import unittest
from unittest.mock import patch

from worker.jobs import process_set


class CatalogueRerunArtistTest(unittest.TestCase):
    def test_rerun_uses_the_sets_existing_artist_not_the_label(self):
        row = {"id": "r", "artist_name": "Catalogue re-run (D06)",
               "source_metadata": {"catalogue_rerun": "d06", "rerun_of_set_id": "s"}}
        with patch.object(process_set, "fetch_one", side_effect=[row, {"name": "Ben UFO"}]) as fetch:
            self.assertEqual(process_set._load_run("r")["artist_name"], "Ben UFO")
        self.assertEqual(fetch.call_args_list[1].args[1], ("s",))

    def test_rerun_without_an_artist_link_gets_none(self):
        row = {"id": "r", "artist_name": "Catalogue re-run (D06)",
               "source_metadata": {"catalogue_rerun": "d06", "rerun_of_set_id": "s"}}
        with patch.object(process_set, "fetch_one", side_effect=[row, None]):
            self.assertIsNone(process_set._load_run("r")["artist_name"])

    def test_curated_artist_name_is_kept(self):
        row = {"id": "r", "artist_name": "Ben UFO", "source_metadata": {}}
        with patch.object(process_set, "fetch_one", return_value=row):
            self.assertEqual(process_set._load_run("r")["artist_name"], "Ben UFO")


if __name__ == "__main__":
    unittest.main()
