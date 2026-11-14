import asyncio
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from worker.jobs import yoon_partial_runner as base
from worker.jobs import yoon_sampling_compare as compare

RATE = base.RATE
SET = sorted(base.SET_IDS)[0]
KEY = 'k' * 40


def fragment(seconds, start=0, index=0):
    frames = seconds * RATE
    return {'index': index, 'frames': frames, 'startFrame': start,
            'parts': [{'file': 'm.wav', 'start': start, 'end': start + frames}]}


def hit(index, key=None):
    raw = {'matches': [{}], 'track': {'key': key, 'title': 'T' + key, 'subtitle': 'A'}} if key else {'matches': []}
    return {'index': index, 'response': {'recognized': key is not None, 'raw_data': raw}}


def arm(name, window, stride):
    return {'name': name, 'window': window, 'stride': stride}


class GridTests(unittest.TestCase):
    def test_arm_grid_uses_window_and_stride(self):
        grid = compare.arm_grid([fragment(120)], arm('a', 12, 6))
        self.assertEqual(len(grid), (120 - 12) // 6 + 1)
        self.assertEqual([w['start_frame'] for w in grid[:3]], [0, 6 * RATE, 12 * RATE])
        self.assertEqual(grid[0]['parts'][0]['end'] - grid[0]['parts'][0]['start'], 12 * RATE)

    def test_constants_restored(self):
        compare.arm_grid([fragment(120)], arm('a', 12, 3))
        self.assertEqual((base.WINDOW_FRAMES, base.HOP_FRAMES), (30 * RATE, 15 * RATE))

    def test_analysed_overlap(self):
        self.assertEqual(compare.analysed_overlap(compare.BASELINE), -0.25)
        self.assertEqual(compare.analysed_overlap(arm('a', 12, 12)), 0)
        self.assertEqual(compare.analysed_overlap(arm('a', 12, 3)), 0.75)
        self.assertEqual(compare.analysed_overlap(arm('a', 30, 6)), 0.5)

    def test_invalid_and_unaligned_arms_rejected(self):
        for bad in (arm('a', 2, 1), arm('a', 12, 13), arm('a', 12, 0), arm('a', '12', 6),
                    arm('a', 12, 1 / 3)):
            with self.assertRaises(SystemExit):
                compare.arm_frames(bad)
        self.assertEqual(compare.arm_frames(arm('a', 30, 7.5)), (30 * RATE, int(7.5 * RATE)))

    def test_request_validation(self):
        ok = {'sets': [SET], 'arms': [arm('w12s6', 12, 6)]}
        self.assertEqual(compare.validate_request(ok)[0], [SET])
        for bad in ({'sets': ['00000000-0000-0000-0000-000000000000'], 'arms': ok['arms']},
                    {'sets': [SET], 'arms': [arm('w30s15', 30, 15)]},
                    {'sets': [SET], 'arms': [arm('a b', 12, 6)]},
                    {'sets': [SET], 'arms': [arm('x', 12, 6), arm('x', 12, 3)]}):
            with self.assertRaises(SystemExit):
                compare.validate_request(bad)


class CountTests(unittest.TestCase):
    def test_identified_counts_with_arm_constants(self):
        a = arm('a', 12, 6)
        grid = compare.arm_grid([fragment(300)], a)
        hits = [hit(w['index'], 'k1' if w['index'] < 8 else 'k2' if w['index'] < 16 else None) for w in grid]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = compare.identified(grid, hits, a)
        self.assertEqual(out.getvalue(), '')  # nothing private printed
        self.assertEqual(result, {'windows': len(grid), 'recognized_windows': 16,
                                  'distinct_tracks': 2, 'identified_entries': 2})

    def test_reduce_hit_keeps_only_cluster_fields(self):
        raw = {'matches': [{'offset': 1}], 'track': {'key': 'k', 'title': 't', 'subtitle': 's',
                                                     'isrc': 'I', 'images': {'x': 'y'}}, 'location': {}}
        self.assertEqual(compare.reduce_hit(4, True, raw)['response']['raw_data'],
                         {'matches': [{}], 'track': {'key': 'k', 'title': 't', 'subtitle': 's', 'isrc': 'I'}})
        self.assertEqual(compare.reduce_hit(4, False, {'matches': []})['response']['raw_data'], {'matches': []})


@unittest.skipUnless(shutil.which('openssl'), 'openssl required')
class SealTests(unittest.TestCase):
    def test_round_trip_and_ciphertext_hides_content(self):
        with patch.dict(os.environ, {'HITS_KEY': KEY}):
            blob = compare.seal({'title': 'Secret Song'})
            self.assertNotIn(b'Secret', blob)
            self.assertEqual(compare.unseal(blob), {'title': 'Secret Song'})

    def test_short_key_refused(self):
        with patch.dict(os.environ, {'HITS_KEY': 'short'}):
            with self.assertRaises(SystemExit):
                compare.seal({})


class FakeRecognizer:
    calls = 0
    instances = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self._quota_cooldown_until = 0
        FakeRecognizer.instances.append(self)

    async def recognize_batch(self, segments, total_segments=None):
        out = []
        for s in segments:
            FakeRecognizer.calls += 1
            r = FakeRecognizer.results(s, FakeRecognizer.calls)
            for _ in range(getattr(r, 'throttles', 0)):
                self.kwargs['on_attempt'](result(429), None, 5.0)
            self.kwargs['on_attempt'](r, None, 0)
            out.append(r)
        return out

    async def close(self):
        pass


def result(status=200, recognized=False, raw=None, throttles=0):
    return SimpleNamespace(http_status=status, is_valid=status == 200, recognized=recognized,
                           throttles=throttles,
                           raw_data=raw if raw is not None else ({'matches': []} if status == 200 else None))


def new_stats():
    return {'calls': 0, 'throttled': 0, 'backoff_seconds': 0.0, 'passes': 0, 'identity_incomplete': 0}


class RecognizeTests(unittest.TestCase):
    def run_windows(self, results, deadline=7800, a=arm('a', 12, 6)):
        grid = compare.arm_grid([fragment(90)], a)
        FakeRecognizer.calls = 0
        FakeRecognizer.instances = []
        FakeRecognizer.results = results
        stats = new_stats()
        def fetch(url, first, last, path):
            size = last - first + 1
            path.write_bytes(b'data' + b'\0' * (size - 4) if first == base.DATA_OFFSET - 8 else b'\0' * size)
        with patch.dict('sys.modules', {'track_recognizer': SimpleNamespace(TrackRecognizer=FakeRecognizer)}), \
                patch.object(base, 'fetch_range', fetch), \
                patch.object(compare.asyncio, 'sleep', new_callable=AsyncMock) as sleep:
            self.sleep = sleep
            hits = asyncio.run(compare.recognize_windows(
                grid, compare.arm_frames(a)[0], {'m.wav': 'x'}, stats,
                compare.time.monotonic() + deadline))
        return grid, hits, stats

    def test_every_window_through_production_retry_path(self):
        grid, hits, stats = self.run_windows(lambda s, n: result())
        self.assertEqual([h['index'] for h in hits], [w['index'] for w in grid])
        kwargs = FakeRecognizer.instances[0].kwargs
        self.assertNotIn('single_attempt', kwargs)
        self.assertIsNotNone(kwargs['continuation_deadline'])
        self.assertEqual((stats['passes'], stats['calls']), (1, len(grid)))

    def test_throttling_is_survived_and_counted(self):
        grid, hits, stats = self.run_windows(lambda s, n: result(throttles=3 if n == 1 else 0))
        self.assertEqual(len(hits), len(grid))
        self.assertEqual((stats['throttled'], stats['backoff_seconds']), (3, 15.0))

    def test_unresolved_window_retried_after_pause_with_same_recognizer(self):
        grid, hits, stats = self.run_windows(lambda s, n: result(429) if n == 2 else result())
        self.assertEqual(len(hits), len(grid))
        self.assertEqual(stats['passes'], 2)
        self.assertEqual(len(FakeRecognizer.instances), 1)
        self.assertGreaterEqual(self.sleep.await_args.args[0], 60)

    def test_incomplete_identity_is_retried_not_fatal(self):
        bad = {'matches': [{}], 'track': {'key': 'x'}}
        grid, hits, stats = self.run_windows(lambda s, n: result(200, True, bad) if n == 1 else result())
        self.assertEqual(len(hits), len(grid))
        self.assertEqual(stats['identity_incomplete'], 1)

    def test_deadline_reports_unresolved_windows(self):
        with self.assertRaisesRegex(compare.Inconclusive, 'deadline_with_'):
            self.run_windows(lambda s, n: result(429), deadline=0)

    def test_window_length_checked(self):
        with self.assertRaisesRegex(RuntimeError, 'window_size_changed'):
            grid = compare.arm_grid([fragment(90)], arm('a', 12, 6))
            FakeRecognizer.results = lambda s, n: result()
            def fetch(url, first, last, path):
                size = last - first + 1
                path.write_bytes(b'data' + b'\0' * (size - 4) if first == base.DATA_OFFSET - 8 else b'\0' * size)
            with patch.dict('sys.modules', {'track_recognizer': SimpleNamespace(TrackRecognizer=FakeRecognizer)}), \
                    patch.object(base, 'fetch_range', fetch):
                asyncio.run(compare.recognize_windows(grid, 30 * RATE, {'m.wav': 'x'}, new_stats(),
                                                      compare.time.monotonic() + 60))


class SourceLinkTests(unittest.TestCase):
    progress = {'released': True, 'fragments': [fragment(60)]}

    def test_released_family_uses_secret_map_only_for_needed_masters(self):
        links = '{"links": [{"name": "m.wav", "href": "https://x/m"}, {"name": "o.wav", "href": "https://x/o"}]}'
        with patch.dict(os.environ, {'SAMPLING_SOURCE_LINKS': links}):
            self.assertEqual(compare.source_links('s', self.progress), {'m.wav': 'https://x/m'})

    def test_missing_master_stops_without_naming_it(self):
        with patch.dict(os.environ, {'SAMPLING_SOURCE_LINKS': '{"links": []}'}):
            with self.assertRaisesRegex(SystemExit, '^1 master link'):
                compare.source_links('s', self.progress)


@unittest.skipUnless(shutil.which('openssl'), 'openssl required')
class CommandTests(unittest.TestCase):
    """plan -> recognize shards -> combine, with the database and provider faked."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        (self.dir / '.github').mkdir()
        self.arms = [arm('w12s6', 12, 6), arm('w30s6', 30, 6)]
        (self.dir / '.github/sampling-compare-request.json').write_text(
            json.dumps({'sets': [SET], 'arms': self.arms}))
        self.fragments = [fragment(600)]
        grid_a = base.windows(self.fragments)
        self.progress = {'released': True, 'fragments': self.fragments, 'expected': len(grid_a)}
        self.evidence = {'hits': [hit(w['index'], 'k%d' % (w['start_frame'] // (120 * RATE))) for w in grid_a]}
        cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, cwd)

    def db(self, name, *args):
        return {'yoon_partial_progress': self.progress, 'yoon_partial_hits_for': self.evidence}[name]

    def test_end_to_end_counts_only(self):
        env = {'HITS_KEY': KEY, 'YOON_PARTIAL_SET_ID': SET, 'PLAN_OUTPUT': str(self.dir / 'plan.json'),
               'SAMPLING_SOURCE_LINKS': '{"links": [{"name": "m.wav", "href": "x"}]}'}
        printed = []
        async def fake_windows(grid, frames, links, stats, deadline):
            stats.update(calls=len(grid), runtime_seconds=0)
            return [hit(w['index'], 'k%d' % (w['start_frame'] // (120 * RATE))) for w in grid]
        with patch.dict(os.environ, env), patch.object(base, 'call', self.db), \
                patch.object(compare, 'SHARD_WINDOWS', 40), \
                patch.object(base, 'say', printed.append), \
                patch.object(compare, 'recognize_windows', fake_windows):
            self.assertEqual(compare.plan(), 0)
            shards = json.loads((self.dir / 'plan.json').read_text())['shards']
            self.assertTrue(all(s['count'] > 1 for s in shards))
            (self.dir / 'hits').mkdir()
            for i, s in enumerate(shards):
                with patch.dict(os.environ, {'SAMPLING_ARM': s['arm'], 'SHARD_INDEX': str(s['index']),
                                             'SHARD_COUNT': str(s['count']),
                                             'HITS_OUTPUT': str(self.dir / 'hits' / f'{i}.bin')}):
                    self.assertEqual(asyncio.run(compare.recognize()), 0)
            with patch.dict(os.environ, {'HITS_DIR': str(self.dir / 'hits')}):
                self.assertEqual(compare.combine(), 0)
        result = json.loads(printed[-1][len('RESULT '):])
        arms = result['arms']
        self.assertEqual(set(arms), {'w30s15', 'w12s6', 'w30s6'})
        self.assertEqual(arms['w30s15']['identified_entries'], 5)
        for name in ('w12s6', 'w30s6'):
            self.assertEqual(arms[name]['identified_entries'], 5)
            self.assertEqual(arms[name]['calls'], arms[name]['windows'])
        self.assertNotIn('Tk', ''.join(printed))

    def test_missing_shard_reports_incomplete(self):
        env = {'HITS_KEY': KEY, 'YOON_PARTIAL_SET_ID': SET, 'HITS_DIR': str(self.dir / 'none')}
        printed = []
        with patch.dict(os.environ, env), patch.object(base, 'call', self.db), \
                patch.object(base, 'say', printed.append):
            compare.combine()
        arms = json.loads(printed[-1][len('RESULT '):])['arms']
        self.assertTrue(arms['w12s6']['status'].startswith('incomplete'))


if __name__ == '__main__':
    unittest.main()
