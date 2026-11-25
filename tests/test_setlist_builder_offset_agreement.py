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
          'DUPLICATE_MERGE_SECONDS': 0.0, 'FALSE_POSITIVE_SCORE_MIN': 0.0}


def build(recs, **values):
    values = {**LEGACY, **values}
    with patch.multiple(Config, **values), contextlib.redirect_stdout(io.StringIO()):
        return SetlistBuilder().build_setlist(recs)


# offset agreement alone; the score filter has its own tests below
PROFILE = {**config.CLUSTERING_PROFILES['offset_agreement'], 'FALSE_POSITIVE_SCORE_MIN': 0.0}
FULL_PROFILE = config.CLUSTERING_PROFILES['offset_agreement']


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
            self.assertEqual(Config.FALSE_POSITIVE_SCORE_MIN, 0.30)
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



class FalsePositiveScoreTests(unittest.TestCase):
    def test_isolated_intro_pair_is_dropped(self):
        # two agreeing hits matched in the first seconds of the track, nothing nearby
        recs = [rec(10, 'p', 5.0), rec(11, 'p', 20.0)]
        self.assertEqual(len(build(recs, **PROFILE)), 1)
        self.assertEqual(build(recs, **{**FULL_PROFILE, 'FALSE_POSITIVE_SCORE_MIN': 0.5}), [])

    def test_long_linear_run_is_kept(self):
        recs = [rec(i, 'r', 60.0 + 15 * (i - 20)) for i in range(20, 30)]
        self.assertEqual([t.detection_count for t in build(recs, **FULL_PROFILE)], [10])

    def test_score_orders_strong_above_weak(self):
        from false_positive_score import score
        base = dict(g=2, n=2, bleed=False, other=0, near_dup=False, ctx=False, gap=300, intro=True,
                    density=1.0, tskew=0.0, fskew=0.0)
        strong = dict(base, g=12, n=12, gap=0, intro=False)
        self.assertLess(score(base), 0.5)
        self.assertGreater(score(strong), 0.5)
        self.assertLess(score(dict(strong, bleed=True, near_dup=True)), score(strong))

    def test_off_by_default_in_build(self):
        recs = [rec(10, 'p', 5.0), rec(11, 'p', 20.0), rec(12, 'p', 35.0)]
        self.assertEqual(len(build(recs)), 1)


if __name__ == '__main__':
    unittest.main()


class TimingExtensionTest(unittest.TestCase):
    """D07b: offset agreement keeps or drops; a kept track is timed from detections that
    connect to the agreeing group (gaps <= OFFSET_TIMING_EXTEND_WINDOWS)."""

    def recs(self):
        # Track 'a' plays windows 0-9; windows 0-3 drift (offsets disagree), 4-9 agree.
        out = [rec(i, 'a', offset=100.0 + i * 3) for i in range(4)]
        out += [rec(i, 'a', offset=float(i * 15 - 30)) for i in range(4, 10)]
        out += [rec(30, 'a', offset=999.0)]  # far-away stray, not connected
        return out

    def test_off_starts_at_agreeing_group(self):
        t, = build(self.recs(), OFFSET_AGREEMENT_MIN=2, MIN_CLUSTER_SIZE=1, MIN_CLUSTER_DENSITY=0.0,
                   OFFSET_TIMING_EXTEND_WINDOWS=0)
        self.assertEqual(t.start_time, 60.0)

    def test_span_extends_timing_but_not_counts(self):
        t, = build(self.recs(), OFFSET_AGREEMENT_MIN=2, MIN_CLUSTER_SIZE=1, MIN_CLUSTER_DENSITY=0.0,
                   OFFSET_TIMING_EXTEND_WINDOWS=8, OFFSET_TIMING_EXTEND_MODE='span')
        self.assertEqual(t.start_time, 0.0)
        self.assertEqual(t.end_time, 9 * 15 + 30)  # the stray at window 30 is not connected
        self.assertEqual(t.detection_count, 6)

    def test_cluster_mode_counts_connected(self):
        t, = build(self.recs(), OFFSET_AGREEMENT_MIN=2, MIN_CLUSTER_SIZE=1, MIN_CLUSTER_DENSITY=0.0,
                   OFFSET_TIMING_EXTEND_WINDOWS=8, OFFSET_TIMING_EXTEND_MODE='cluster')
        self.assertEqual(t.start_time, 0.0)
        self.assertEqual(t.detection_count, 10)

    def test_profile_enables_d07b_span8(self):
        self.assertEqual(config.CLUSTERING_PROFILES['offset_agreement']['OFFSET_TIMING_EXTEND_WINDOWS'], 8)
        self.assertEqual(config.CLUSTERING_PROFILES['offset_agreement']['OFFSET_TIMING_EXTEND_MODE'], 'span')


def rec_fs(index, key, offset, fskew=0.0):
    r = rec(index, key, offset)
    r.raw_data['matches'][0]['frequencyskew'] = fskew
    return r


D07C_OFF = {**PROFILE, 'SAMPLE_YIELD_MAX_AGREEING': 0, 'LOOP_RESCUE_RUN': 0}


class SampleYieldTests(unittest.TestCase):
    """D07c: Highkin Sunday 1:15:15, Bar-Kays sample wrapped around Funktastics."""

    def recs(self):
        # sample: 4 of 10 detections agree (windows 11-14), extended by D07b to 1-17
        sample = [rec(1, 's', 25.7), rec(2, 's', 29.8), rec(3, 's', 33.9), rec(5, 's', 9.3),
                  rec(7, 's', 180.6), rec(8, 's', 184.7), rec(9, 's', 36.4),
                  rec(11, 's', 120.7), rec(12, 's', 135.6), rec(13, 's', 150.6), rec(14, 's', 165.6),
                  rec(15, 's', 93.4), rec(16, 's', 108.3), rec(17, 's', 112.4)]
        # host: 3 of 3 agree at windows 4, 6, 10
        host = [rec(4, 'h', 80.9), rec(6, 'h', 111.0), rec(10, 'h', 171.2)]
        return sample + host

    def test_off_keeps_sample_on_top(self):
        titles = [t.title for t in build(self.recs(), **D07C_OFF)]
        self.assertIn('ts', titles)

    def test_sample_yields_and_host_takes_its_span(self):
        tracks = build(self.recs(), **PROFILE)
        self.assertEqual([t.title for t in tracks], ['th'])
        self.assertEqual((tracks[0].start_time, tracks[0].end_time), (15.0, 285.0))

    def test_well_agreeing_track_never_yields(self):
        # 8 agreeing detections is above the cap: no yield even when wrapped
        recs = [rec(i, 's', 100.0 + 15 * i) for i in (1, 2, 3, 14, 15, 16, 17, 18)] + \
               [rec(i, 'h', 15.0 * i) for i in (6, 7, 8)]
        self.assertIn('ts', [t.title for t in build(recs, **PROFILE)])

    def test_far_away_detections_do_not_stretch_host(self):
        # the weak track's detections are far from the host: no wrap, no yield
        recs = [rec(1, 's', 10.0), rec(2, 's', 25.0), rec(60, 's', 300.0), rec(61, 's', 1.0),
                rec(62, 's', 400.0)] + [rec(i, 'h', 15.0 * i) for i in (30, 31, 32)]
        tracks = build(recs, **PROFILE)
        host = [t for t in tracks if t.title == 'th'][0]
        self.assertEqual(host.start_time, 450.0)


class LoopRescueTests(unittest.TestCase):
    """D07c: Highkin Sunday 30:15, She Knew in looped D&B sections."""

    she_knew = [(121, 10.98, 0.0021), (122, 163.99, 0.0027), (123, 21.77, 0.0015),
                (124, 166.46, 0.0020), (125, 16.02, 0.0031), (131, 34.66, 0.0043)]

    def test_looped_run_is_kept(self):
        recs = [rec_fs(i, 'k', o, f) for i, o, f in self.she_knew]
        self.assertEqual(build(recs, **D07C_OFF), [])
        tracks = build(recs, **PROFILE)
        self.assertEqual([(t.title, t.start_time) for t in tracks], [('tk', 1815.0)])

    def test_frozen_fragment_is_not_rescued(self):
        # one fragment matched over and over: offsets barely move
        recs = [rec_fs(i, 'f', 200.0 + 2 * n) for n, i in enumerate(range(40, 46))]
        self.assertEqual(build(recs, **PROFILE), [])

    def test_pitched_run_is_not_rescued(self):
        recs = [rec_fs(i, 'p', o, 0.03) for i, o, _ in self.she_knew]
        self.assertEqual(build(recs, **PROFILE), [])

    def test_short_run_is_not_rescued(self):
        recs = [rec_fs(i, 'k', o, f) for i, o, f in self.she_knew[:4]]
        self.assertEqual(build(recs, **PROFILE), [])

    def test_rescue_never_lands_inside_a_listed_track(self):
        verified = [rec(i, 'v', 15.0 * (i - 100)) for i in range(100, 140, 4)]
        recs = [rec_fs(i, 'k', o, f) for i, o, f in self.she_knew] + verified
        self.assertEqual([t.title for t in build(recs, **PROFILE)], ['tv'])
