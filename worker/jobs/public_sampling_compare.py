"""D07 round 3: sampling-grid comparison on public (non-Yoon) sets.

Every arm, the production 30 s / 15 s grid included, is recognized fresh from
the same downloaded audio, so all arms are comparable and the raw per-window
hits can be replayed offline against independent tracklists. Production parity:
audio comes from the production AudioDownloader (yt-dlp, mix.mp3) and windows
from the production AudioSegmenter ffmpeg extraction (128k mp3, 44.1 kHz). Only
segment duration and stride differ per arm. Recognition uses the shared
throttle-aware loop in yoon_sampling_compare (exponential 429 backoff, never an
abort on throttling).

No database access at all. Logs carry counts only. Audio and hits pass between
jobs only as AES-256 encrypted artifacts (key derived from the
SAMPLING_SOURCE_LINKS secret) that expire after five days. Analysis and
tracklist scoring happen offline.

  python -m worker.jobs.public_sampling_compare plan       # matrix JSON
  python -m worker.jobs.public_sampling_compare fetch      # one set -> sealed audio
  python -m worker.jobs.public_sampling_compare recognize  # one (set, arm, shard)
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid

from worker.jobs import yoon_partial_runner as base
from worker.jobs import yoon_sampling_compare as study

REQUEST = Path('.github/public-sampling-request.json')
SHARD_WINDOWS = int(os.getenv('SHARD_WINDOWS', '120'))
MAX_JOBS = 250
MAX_SET_SECONDS = 4 * 3600


def arm_seconds(arm: dict) -> tuple[int, int]:
    """Production segmenter takes whole seconds: duration and overlap."""
    window, stride = arm['window'], arm['stride']
    if not (type(window) is int and type(stride) is int and 3 <= window <= 60
            and 1 <= stride <= window):
        raise SystemExit('arm_parameters_invalid')
    return window, window - stride


def validate_request(request: dict) -> tuple[list[dict], list[dict]]:
    sets = request['sets']
    if not 1 <= len(sets) <= 16:
        raise SystemExit('request_sets_invalid')
    ids = []
    for item in sets:
        ids.append(str(uuid.UUID(item['id'])))
        url = item['url']
        if not (isinstance(url, str) and url.startswith(('https://www.youtube.com/watch?v=',
                                                          'https://soundcloud.com/'))):
            raise SystemExit('request_url_invalid')
        if not (type(item['seconds']) in (int, float) and 60 <= item['seconds'] <= MAX_SET_SECONDS):
            raise SystemExit('request_duration_invalid')
    if len(set(ids)) != len(ids):
        raise SystemExit('request_sets_duplicate')
    arms = request['arms']
    names = [a['name'] for a in arms]
    if not 1 <= len(arms) <= 8 or len(set(names)) != len(names):
        raise SystemExit('request_arms_invalid')
    for arm in arms:
        if not (isinstance(arm['name'], str) and arm['name'].isascii() and arm['name'].isalnum()
                and len(arm['name']) <= 16):
            raise SystemExit('request_arm_name_invalid')
        arm_seconds(arm)
    return sets, arms


def load_request():
    return validate_request(json.loads(REQUEST.read_text()))


def segmenter(arm: dict, work: Path):
    from audio_segmenter import AudioSegmenter
    duration, overlap = arm_seconds(arm)
    seg = AudioSegmenter(segment_duration=duration, overlap=max(overlap, 1))
    seg.overlap = overlap  # the constructor treats 0 as "use the default"
    seg.assets_dir = work
    return seg


def arm_grid(seconds: float, arm: dict) -> list[dict]:
    """Production segment indices and timestamps for this arm."""
    duration, overlap = arm_seconds(arm)
    step = duration - overlap
    if seconds <= duration:
        total = 1
    else:
        total = math.ceil((seconds * 1000 - duration * 1000) / (step * 1000)) + 1
    return [{'index': i, 'start_frame': i * step * base.RATE, 'start_seconds': i * step,
             'duration': duration} for i in range(total)]


def reduce_public(index: int, recognized: bool, raw: dict) -> dict:
    """Identity plus numeric match geometry for offline confidence filters."""
    hit = study.reduce_hit(index, recognized, raw)
    if recognized:
        hit['response']['raw_data']['matches'] = [
            {k: m[k] for k in ('offset', 'timeskew', 'frequencyskew')
             if isinstance(m, dict) and type(m.get(k)) in (int, float)}
            for m in (raw.get('matches') or [])][:5] or [{}]
    return hit


def plan() -> int:
    sets, arms = load_request()
    shards = []
    for item in sets:
        for arm in arms:
            n = len(arm_grid(item['seconds'], arm))
            count = math.ceil(n / SHARD_WINDOWS)
            shards += [{'set': item['id'], 'arm': arm['name'], 'index': i, 'count': count}
                       for i in range(count)]
            base.say(f'{item["id"][:8]} {arm["name"]}: ~{n} windows in {count} shard(s)')
    if len(shards) > MAX_JOBS:
        raise SystemExit(f'{len(shards)} shard jobs exceed {MAX_JOBS}')
    Path(os.environ.get('PLAN_OUTPUT', 'plan.json')).write_text(json.dumps(
        {'shards': shards, 'sets': [s['id'] for s in sets]}))
    return 0


def fetch() -> int:
    from audio_downloader import AudioDownloader
    sets, _ = load_request()
    item = next(s for s in sets if s['id'] == os.environ['SAMPLING_SET_ID'])
    work = Path(tempfile.mkdtemp(prefix='public-sampling-'))
    try:
        downloader = AudioDownloader()
        downloader.assets_dir = work
        with contextlib.redirect_stdout(io.StringIO()):  # yt-dlp verbose output stays out of logs
            audio = downloader.download(item['url'], work / 'mix.mp3')
        seconds = study_duration(audio)
        if abs(seconds - item['seconds']) > 0.02 * item['seconds'] + 5:
            raise SystemExit(f'duration_mismatch: {round(seconds)} s vs {round(item["seconds"])} s')
        out = Path(os.environ.get('AUDIO_OUTPUT', 'audio.bin'))
        out.write_bytes(study._openssl([], audio.read_bytes()))
        base.say(f'{item["id"][:8]}: fetched {round(seconds)} s of audio '
                 f'({round(audio.stat().st_size / 1e6)} MB)')
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def study_duration(audio: Path) -> float:
    from audio_segmenter import AudioSegmenter
    return AudioSegmenter.get_audio_duration_ffprobe(audio)


async def recognize() -> int:
    sets, arms = load_request()
    sid = os.environ['SAMPLING_SET_ID']
    item = next(s for s in sets if s['id'] == sid)
    arm = next(a for a in arms if a['name'] == os.environ['SAMPLING_ARM'])
    index, count = int(os.environ['SHARD_INDEX']), int(os.environ['SHARD_COUNT'])
    if not 0 <= index < count:
        raise SystemExit('shard_bounds')
    work = Path(tempfile.mkdtemp(prefix='public-sampling-'))
    try:
        audio = work / 'mix.mp3'
        audio.write_bytes(study._openssl(['-d'], Path(os.environ['AUDIO_INPUT']).read_bytes()))
        seconds = study_duration(audio)
        grid = arm_grid(seconds, arm)
        lo, hi = base.shard_bounds(len(grid), index, count)
        seg = segmenter(arm, work)

        def write_segment(w, path):
            seg._extract_segment_ffmpeg(audio, float(w['start_seconds']), float(w['duration']), path)

        stats = {'calls': 0, 'throttled': 0, 'backoff_seconds': 0.0, 'passes': 0,
                 'identity_incomplete': 0, 'unresolved': 0}
        started = time.monotonic()
        segments_dir = work / 'segments'
        segments_dir.mkdir()
        hits = await study.recognize_segments(grid[lo:hi], write_segment, '.mp3', segments_dir,
                                              stats, started + study.STUDY_DEADLINE_SECONDS,
                                              reduce=reduce_public)
        stats['runtime_seconds'] = round(time.monotonic() - started)
        payload = {'set': sid, 'arm': arm['name'], 'window': arm['window'], 'stride': arm['stride'],
                   'audio_seconds': seconds, 'windows_total': len(grid), 'index': index,
                   'count': count, 'lo': lo, 'hi': hi,
                   'starts': [w['start_seconds'] for w in grid[lo:hi]], 'hits': hits, 'stats': stats}
        Path(os.environ.get('HITS_OUTPUT', 'hits.bin')).write_bytes(study.seal(payload))
        base.say(f'{sid[:8]} {arm["name"]} shard {index + 1}/{count}: {len(hits)} windows, '
                 + json.dumps(stats))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run(argv: list[str]) -> int:
    if argv == ['plan']:
        return plan()
    if argv == ['fetch']:
        return fetch()
    if argv == ['recognize']:
        try:
            return asyncio.run(recognize())
        except study.Inconclusive as exc:  # counts only, no private data
            base.say(f'INCONCLUSIVE: {exc}')
            return 4
    raise SystemExit('usage: plan | fetch | recognize')


def main(argv: list[str]) -> int:
    base.quiet_process()
    try:
        return run(argv)
    except SystemExit as stop:
        if isinstance(stop.code, str):
            base.say(f'stopped: {stop.code}')
            raise SystemExit(2)
        raise
    except BaseException as error:
        base.say(f'failed: {type(error).__name__}')
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
