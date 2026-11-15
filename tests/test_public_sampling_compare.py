import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from worker.jobs import public_sampling_compare as pub
from worker.jobs import yoon_partial_runner as base
from worker.jobs import yoon_sampling_compare as study

KEY = '{"links": [{"name": "m.wav", "href": "https://example.invalid/m"}]}'
SET = '11111111-2222-4333-8444-555555555555'
ARMS = [{'name': 'w30s15', 'window': 30, 'stride': 15}, {'name': 'w12s12', 'window': 12, 'stride': 12},
        {'name': 'w12s6', 'window': 12, 'stride': 6}]


def request(**over):
    r = {'sets': [{'id': SET, 'url': 'https://www.youtube.com/watch?v=abc', 'seconds': 600}], 'arms': ARMS}
    r.update(over)
    return r


class GridTests(unittest.TestCase):
    def test_grid_matches_production_segmenter_counts_and_timestamps(self):
        from audio_segmenter import AudioSegmenter
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work)
        for arm in ARMS + [{'name': 'x', 'window': 12, 'stride': 9}]:
            for seconds in (5, 600, 600.4, 3725.7):
                duration, overlap = pub.arm_seconds(arm)
                if overlap:
                    ref = AudioSegmenter(segment_duration=duration, overlap=overlap)
                    ref.assets_dir = work
                    grid = pub.arm_grid(seconds, arm)
                    self.assertEqual(len(grid), ref.calculate_total_segments(seconds))
                    self.assertEqual([w['start_seconds'] for w in grid[:3]],
                                     [ref._segment_info(i)['timestamp'] for i in range(min(3, len(grid)))])

    def test_zero_overlap_is_not_replaced_by_default(self):
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work)
        seg = pub.segmenter({'name': 'a', 'window': 12, 'stride': 12}, work)
        self.assertEqual((seg.segment_duration, seg.overlap), (12, 0))
        self.assertEqual(seg._segment_info(2)['timestamp'], 24.0)
        self.assertEqual(len(pub.arm_grid(120, {'name': 'a', 'window': 12, 'stride': 12})), 10)

    def test_request_validation(self):
        self.assertEqual(len(pub.validate_request(request())[1]), 3)
        for bad in (request(sets=[{'id': SET, 'url': 'http://evil.example/x', 'seconds': 600}]),
                    request(sets=[{'id': SET, 'url': 'https://soundcloud.com/a/b', 'seconds': 99999}]),
                    request(arms=[{'name': 'a', 'window': 12, 'stride': 7.5}]),
                    request(arms=[{'name': 'a b', 'window': 12, 'stride': 6}]),
                    request(arms=[ARMS[0], ARMS[0]])):
            with self.assertRaises(SystemExit):
                pub.validate_request(bad)

    def test_reduce_keeps_identity_and_numeric_match_geometry_only(self):
        raw = {'matches': [{'id': 'x', 'offset': 12.5, 'timeskew': 0.01, 'frequencyskew': 0.0, 'other': 'y'}],
               'track': {'key': 'k', 'title': 't', 'subtitle': 's', 'images': {}}, 'location': {}}
        hit = pub.reduce_public(3, True, raw)
        self.assertEqual(hit['response']['raw_data'],
                         {'matches': [{'offset': 12.5, 'timeskew': 0.01, 'frequencyskew': 0.0}],
                          'track': {'key': 'k', 'title': 't', 'subtitle': 's'}})
        self.assertEqual(pub.reduce_public(3, False, {})['response']['raw_data'], {'matches': []})


@unittest.skipUnless(shutil.which('openssl'), 'openssl required')
class CommandTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        (self.dir / '.github').mkdir()
        (self.dir / '.github/public-sampling-request.json').write_text(json.dumps(request()))
        cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, cwd)

    def test_plan_shards_every_arm(self):
        with patch.dict(os.environ, {'PLAN_OUTPUT': str(self.dir / 'plan.json')}), \
                patch.object(pub, 'SHARD_WINDOWS', 40), patch.object(base, 'say'):
            pub.plan()
        plan = json.loads((self.dir / 'plan.json').read_text())
        self.assertEqual(plan['sets'], [SET])
        self.assertEqual({s['arm'] for s in plan['shards']}, {'w30s15', 'w12s12', 'w12s6'})
        self.assertEqual(sum(1 for s in plan['shards'] if s['arm'] == 'w12s6'), 3)  # 99 windows / 40

    def test_fetch_seals_audio_and_logs_counts_only(self):
        printed = []
        def fake_download(self, url, output_path=None):
            output_path.write_bytes(b'ID3 fake audio bytes')
            print('Downloading private-looking title')  # must not reach logs
            return output_path
        with patch.dict(os.environ, {'SAMPLING_SET_ID': SET, 'SAMPLING_SOURCE_LINKS': KEY,
                                     'AUDIO_OUTPUT': str(self.dir / 'audio.bin')}), \
                patch('audio_downloader.AudioDownloader.download', fake_download), \
                patch.object(pub, 'study_duration', return_value=600.0), \
                patch.object(base, 'say', printed.append):
            self.assertEqual(pub.fetch(), 0)
            blob = (self.dir / 'audio.bin').read_bytes()
            self.assertNotIn(b'fake audio', blob)
            self.assertEqual(study._openssl(['-d'], blob), b'ID3 fake audio bytes')
        self.assertEqual(len(printed), 1)
        self.assertIn('fetched 600 s', printed[0])

    def test_recognize_shard_uses_segmenter_and_seals_hits(self):
        with patch.dict(os.environ, {'SAMPLING_SOURCE_LINKS': KEY}):
            (self.dir / 'audio.bin').write_bytes(study._openssl([], b'ID3 audio'))
        calls = []
        def extract(self, audio, start, duration, out):
            calls.append((start, duration))
            out.write_bytes(b'mp3')
        async def fake_segments(grid, write_segment, suffix, work, stats, deadline, reduce=None):
            out = []
            for w in grid:
                path = work / f'w{w["index"]}{suffix}'
                write_segment(w, path)
                stats['calls'] += 1
                out.append(reduce(w['index'], False, {}))
            return out
        env = {'SAMPLING_SET_ID': SET, 'SAMPLING_ARM': 'w12s6', 'SHARD_INDEX': '1', 'SHARD_COUNT': '3',
               'SAMPLING_SOURCE_LINKS': KEY, 'AUDIO_INPUT': str(self.dir / 'audio.bin'),
               'HITS_OUTPUT': str(self.dir / 'hits.bin')}
        with patch.dict(os.environ, env), patch.object(pub, 'study_duration', return_value=600.0), \
                patch('audio_segmenter.AudioSegmenter._extract_segment_ffmpeg', extract), \
                patch.object(study, 'recognize_segments', fake_segments), patch.object(base, 'say'):
            self.assertEqual(asyncio.run(pub.recognize()), 0)
            payload = study.unseal((self.dir / 'hits.bin').read_bytes())
        self.assertEqual((payload['windows_total'], payload['lo'], payload['hi']), (99, 33, 66))
        self.assertEqual(len(payload['hits']), 33)
        self.assertEqual(calls[0], (198.0, 12.0))
        self.assertEqual(payload['starts'][0], 198)


class MainTests(unittest.TestCase):
    def test_reason_logged_and_errors_redacted(self):
        printed = []
        with patch.object(base, 'quiet_process'), patch.object(base, 'say', printed.append):
            with patch.object(pub, 'run', side_effect=SystemExit('request_url_invalid')):
                with self.assertRaises(SystemExit):
                    pub.main(['plan'])
            with patch.object(pub, 'run', side_effect=ValueError('secret detail')):
                self.assertEqual(pub.main(['plan']), 1)
        self.assertEqual(printed, ['stopped: request_url_invalid', 'failed: ValueError'])


if __name__ == '__main__':
    unittest.main()
