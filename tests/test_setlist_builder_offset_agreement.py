import contextlib
import io
import unittest
from unittest.mock import patch

import config
from config import Config
from setlist_builder import SetlistBuilder, Track
from worker.pipeline.models import Recognition


def rec(index, key, offset=None, stride=15):
    raw = {'matches': [{'offset': offset}] if offset is not None else [{}],
           'track': {'key': key, 'title': f't{key}', 'subtitle': f'a{key}'}}
    return Recognition(timestamp=float(index * stride), track_title=f't{key}', artist=f'a{key}',
                       shazam_track_id=key, raw_data=raw, recognized=True, segment_index=index)


LEGACY = {'MIN_CLUSTER_SIZE': 3, 'MIN_CLUSTER_DENSITY': 0.25, 'OVERLAP_RESOLUTION_ENABLED': True,
          'OVERLAP_THRESHOLD': 0.3, 'OFFSET_AGREEMENT_MIN': 0, 'OFFSET_AGREEMENT_SECONDS': 4.0,
          'DUPLICATE_MERGE_SECONDS': 0.0}


def build(recs, **values):
    values = {**LEGACY, **values}
    with patch.multiple(Config, **values), contextlib.redirect_stdout(io.StringIO()):
        return SetlistBuilder().build_setlist(recs)


PROFILE = config.CLUSTERING_PROFILES['offset_agreement']


class OffsetAgreementTests(unittest.TestCase):
    def test_default_profile_is_legacy(self):
        import os
        if not os.getenv('CLUSTERING_PROFILE'):
            self.assertEqual((Config.MIN_CLUSTER_SIZE, Config.OFFSET_AGREEMENT_MIN), (3, 0))

    def test_legacy_rules_ignore_offsets(self):
        recs = [rec(0, 'x', 10), rec(1, 'x', 500), rec(2, 'x', 900)]
        self.assertEqual(len(build(recs)), 1)  # legacy: 3 detections pass

    def test_two_agreeing_detections_make_a_track(self):
        # set time advances 15 s and the track offset advances ~15 s: same playback
        recs = [rec(10, 'x', 30.0), rec(11, 'x', 45.5)]
        tracks = build(recs, **PROFILE)
        self.assertEqual([(t.title, t.detection_count) for t in tracks], [('tx', 2)])

    def test_scattered_detections_are_dropped(self):
        # same track id at offsets that do not advance with set time
        recs = [rec(10, 'y', 200.0), rec(40, 'y', 20.0), rec(80, 'y', 330.0)]
        self.assertEqual(build(recs, **PROFILE), [])
        self.assertEqual(build(recs), [])  # legacy drops it too, by density (3 / 71)

    def test_single_detection_is_dropped(self):
        self.assertEqual(build([rec(5, 'z', 12.0)], **PROFILE), [])

    def test_missing_offsets_do_not_agree(self):
        self.assertEqual(build([rec(5, 'z'), rec(6, 'z')], **PROFILE), [])

    def test_track_keeps_only_agreeing_detections(self):
        recs = [rec(3, 'w', 400.0), rec(20, 'w', 30.0), rec(21, 'w', 45.0), rec(22, 'w', 61.0)]
        [track] = build(recs, **PROFILE)
        self.assertEqual(track.segment_indices, [20, 21, 22])
        self.assertEqual(track.start_time, 300.0)

    def test_overlap_resolution_still_applies_after_offset_filter(self):
        a = [rec(i, 'a', 15.0 * (i - 10)) for i in range(10, 20)]
        b = [rec(i, 'b', 15.0 * (i - 14)) for i in range(14, 18)]
        self.assertEqual({t.shazam_track_id for t in build(a + b, **PROFILE)}, {'a'})
        self.assertEqual({t.shazam_track_id for t in build(a + b, **PROFILE, OVERLAP_RESOLUTION_ENABLED=False)},
                         {'a', 'b'})

    def test_two_equal_groups_keep_one_instead_of_neither(self):
        # a looped section: anchors 845 and 700 (five each); a median (772) matches neither
        recs = [rec(i, 'n', 15.0 * i - 845) for i in range(60, 65)] + \
               [rec(i, 'n', 15.0 * i - 700) for i in range(65, 70)]
        [track] = build(recs, **PROFILE)
        self.assertEqual(track.segment_indices, [60, 61, 62, 63, 64])

    def test_profiles(self):
        with patch.multiple(Config, **LEGACY):
            config.apply_clustering_profile('')
            self.assertEqual(Config.MIN_CLUSTER_SIZE, 3)
            config.apply_clustering_profile('offset_agreement')
            self.assertEqual((Config.MIN_CLUSTER_SIZE, Config.MIN_CLUSTER_DENSITY,
                              Config.OVERLAP_RESOLUTION_ENABLED, Config.OFFSET_AGREEMENT_MIN),
                             (1, 0.0, True, 2))
            self.assertEqual(Config.DUPLICATE_MERGE_SECONDS, 300.0)
            with self.assertRaises(ValueError):
                config.apply_clustering_profile('typo')


def track(artist, title, start, n):
    return Track(title=title, artist=artist, start_time=float(start), end_time=None, confidence='LOW',
                 detection_count=n, shazam_track_id=None, isrc=None, cluster_density=0.0,
                 cluster_span=1, segment_indices=[int(start // 15)])


def merge(tracks, seconds=300.0):
    with patch.multiple(Config, DUPLICATE_MERGE_SECONDS=seconds), contextlib.redirect_stdout(io.StringIO()):
        return SetlistBuilder()._merge_duplicate_versions(tracks)


class DuplicateMergeTests(unittest.TestCase):
    def test_remix_bleeding_in_collapses_to_the_stronger_entry(self):
        out = merge([track('Florence + the Machine', 'Spectrum', 510, 3),
                     track('Florence + the Machine', 'Spectrum (Say My Name) [Maya Jane Coles Remix]', 585, 6)])
        self.assertEqual([(t.title, t.start_time) for t in out],
                         [('Spectrum (Say My Name) [Maya Jane Coles Remix]', 585.0)])

    def test_tie_keeps_the_later_entry(self):
        out = merge([track('Alan Morris', '7th Morning', 345, 4), track('Alan Morris', '7th Morning (Extended Mix)', 525, 4)])
        self.assertEqual([t.start_time for t in out], [525.0])

    def test_far_apart_or_different_tracks_are_kept(self):
        tracks = [track('A', 'Song', 0, 3), track('A', 'Song', 900, 3), track('B', 'Song', 30, 3), track('A', 'Other', 60, 3)]
        self.assertEqual(len(merge(tracks)), 4)

    def test_off_by_default_in_build(self):
        recs = [rec(i, 'k1') for i in range(4)]
        self.assertEqual(len(build(recs)), 1)


if __name__ == '__main__':
    unittest.main()
