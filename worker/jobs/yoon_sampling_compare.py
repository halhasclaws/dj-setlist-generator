"""D07 sampling-grid comparison on sealed partial Yoon families.

The installed SDK fingerprints a centred 12 s segment of whatever window it is
given (shazamio_core SearchParams default). A window's stride therefore sets the
overlap between analysed regions: overlap = 1 - stride / min(window, 12 s).
The production grid (30 s windows every 15 s) leaves 3 s gaps. This study runs
several arms, each a (window seconds, stride seconds) grid over the same master
audio, and compares them with the recorded production evidence (baseline arm).

Every arm uses the same encoding (24-bit stereo 44.1 kHz WAV cut from the pinned
master), the production throttle-aware TrackRecognizer (exponential 429 backoff,
Retry-After, shared cooldown; throttling is survived, never an abort) and the
same clustering. Only the grid differs.

Safety and privacy:
  * Read-only on the database; links come from the SAMPLING_SOURCE_LINKS secret
    once a family is released (the DB seals them).
  * The repository and its logs are public: logs carry counts only. Shard hits
    pass between jobs only as AES-256 encrypted artifacts (key: HITS_KEY secret
    material), are reduced to what clustering needs, and expire after one day.

  python -m worker.jobs.yoon_sampling_compare plan       # writes matrix JSON
  python -m worker.jobs.yoon_sampling_compare recognize  # one (set, arm, shard)
  python -m worker.jobs.yoon_sampling_compare combine    # one set, all arms
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from recognition_retry_policy import throttle_delay
from worker.jobs import yoon_partial_runner as base

RATE = base.RATE
ANALYSIS_SECONDS = 12
STUDY_DEADLINE_SECONDS = int(os.getenv('STUDY_DEADLINE_SECONDS', '19800'))
MAX_RETRY_SECONDS = int(os.getenv('MAX_RETRY_SECONDS', '1800'))
SHARD_WINDOWS = int(os.getenv('SHARD_WINDOWS', '120'))
MAX_ARM_WINDOWS = int(os.getenv('MAX_ARM_WINDOWS', '2000'))
MAX_JOBS = 250
BASELINE = {'name': 'w30s15', 'window': 30, 'stride': 15}


class Inconclusive(RuntimeError):
    pass


# ---------------------------------------------------------------- grids

def arm_frames(arm: dict) -> tuple[int, int]:
    window, stride = arm['window'], arm['stride']
    if not (type(window) in (int, float) and type(stride) in (int, float)
            and 3 <= window <= 60 and 1 <= stride <= window):
        raise SystemExit('arm_parameters_invalid')
    frames = (round(window * RATE), round(stride * RATE))
    if frames[0] != window * RATE or frames[1] != stride * RATE:
        raise SystemExit('arm_parameters_not_frame_aligned')
    return frames


def analysed_overlap(arm: dict) -> float:
    return round(1 - arm['stride'] / min(arm['window'], ANALYSIS_SECONDS), 3)


@contextlib.contextmanager
def grid_constants(window_frames: int, hop_frames: int):
    """Run the production grid/cluster helpers with another window and hop.

    They read module constants at call time; callers here are synchronous.
    """
    saved = base.WINDOW_FRAMES, base.HOP_FRAMES
    base.WINDOW_FRAMES, base.HOP_FRAMES = window_frames, hop_frames
    try:
        yield
    finally:
        base.WINDOW_FRAMES, base.HOP_FRAMES = saved


def arm_grid(fragments: list[dict], arm: dict) -> list[dict]:
    with grid_constants(*arm_frames(arm)):
        return base.windows(fragments)


def validate_request(request: dict) -> tuple[list[str], list[dict]]:
    import uuid
    sets = [str(uuid.UUID(s)) for s in request['sets']]
    if not 1 <= len(sets) <= 6 or len(set(sets)) != len(sets) or not set(sets) <= base.SET_IDS:
        raise SystemExit('request_sets_invalid')
    arms = request['arms']
    names = [a['name'] for a in arms]
    if not 1 <= len(arms) <= 8 or len(set(names)) != len(names) or BASELINE['name'] in names:
        raise SystemExit('request_arms_invalid')
    for arm in arms:
        if not (isinstance(arm['name'], str) and arm['name'].isascii() and arm['name'].isalnum()
                and len(arm['name']) <= 16):
            raise SystemExit('request_arm_name_invalid')
        arm_frames(arm)
    return sets, arms


# ---------------------------------------------------------------- counting

def reduce_hit(index: int, recognized: bool, raw: dict) -> dict:
    """Only what clustering and counting read."""
    track = raw.get('track') or {}
    slim = {'matches': [{}] if recognized else []}
    if recognized:
        slim['track'] = {k: track[k] for k in ('key', 'title', 'subtitle') if k in track}
        if track.get('isrc'):
            slim['track']['isrc'] = track['isrc']
    return {'index': index, 'response': {'recognized': recognized, 'raw_data': slim}}


def identified(grid: list[dict], hits: list[dict], arm: dict) -> dict:
    with grid_constants(*arm_frames(arm)), contextlib.redirect_stdout(io.StringIO()):
        entries = base.cluster(grid, hits)  # SetlistBuilder prints titles: silenced
    recognized = [h for h in hits if h['response']['recognized']]
    keys = {h['response']['raw_data']['track']['key'] for h in recognized}
    return {'windows': len(grid), 'recognized_windows': len(recognized),
            'distinct_tracks': len(keys), 'identified_entries': len(entries)}


# ---------------------------------------------------------------- encryption

def _openssl(args: list[str], data: bytes) -> bytes:
    key = os.environ.get('HITS_KEY') or ''
    if len(key) < 32:
        raise SystemExit('hits_key_missing')
    return subprocess.run(['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-iter', '200000',
                           '-salt', *args, '-pass', 'env:HITS_KEY'],
                          input=data, capture_output=True, check=True).stdout


def seal(payload: dict) -> bytes:
    return _openssl([], json.dumps(payload).encode())


def unseal(blob: bytes) -> dict:
    return json.loads(_openssl(['-d'], blob))


# ---------------------------------------------------------------- recognition

def source_links(sid: str, progress: dict) -> dict:
    if not progress['released']:
        return base.call('yoon_partial_sources_for', sid)
    raw = os.environ.get('SAMPLING_SOURCE_LINKS') or ''
    if not raw:
        raise SystemExit('family released and SAMPLING_SOURCE_LINKS not configured')
    supplied = {v['name']: v['href'] for v in json.loads(raw)['links']}
    needed = {part['file'] for f in progress['fragments'] for part in f['parts']}
    missing = needed - supplied.keys()
    if missing:
        raise SystemExit(f'{len(missing)} master link(s) missing from SAMPLING_SOURCE_LINKS')
    return {name: supplied[name] for name in needed}


async def recognize_windows(grid: list[dict], window_frames: int, links: dict,
                            stats: dict, deadline: float) -> list[dict]:
    """Every window through the production throttle-aware recognizer.

    One recognizer keeps its shared cooldown for the whole shard. Windows still
    unresolved when a retry budget ends get further passes, each after an
    exponential pause, until the deadline.
    """
    from track_recognizer import TrackRecognizer
    work = Path(tempfile.mkdtemp(prefix='yoon-sampling-'))
    done: dict[int, dict] = {}
    try:
        spans: dict[str, list[int]] = {}
        for w in grid:
            for part in w['parts']:
                span = spans.setdefault(part['file'], [part['start'], part['end']])
                span[0], span[1] = min(span[0], part['start']), max(span[1], part['end'])
        for name in sorted(spans):
            header = work / 'header.bin'
            header.unlink(missing_ok=True)
            base.fetch_range(links[name], base.DATA_OFFSET - 8, base.DATA_OFFSET - 1, header)
            if header.read_bytes()[:4] != b'data':
                raise RuntimeError('source_data_offset_changed')
        local = {}
        for name, (start, end) in sorted(spans.items()):
            path = work / f'{len(local)}.pcm'
            base.fetch_range(links[name], base.DATA_OFFSET + start * base.ALIGN,
                             base.DATA_OFFSET + end * base.ALIGN - 1, path)
            local[name] = (start, path)

        def window_pcm(w):
            pcm = bytearray()
            for part in w['parts']:
                first, path = local[part['file']]
                with path.open('rb') as handle:
                    handle.seek((part['start'] - first) * base.ALIGN)
                    pcm.extend(handle.read((part['end'] - part['start']) * base.ALIGN))
            if len(pcm) != window_frames * base.ALIGN:
                raise RuntimeError('window_size_changed')
            return bytes(pcm)

        def on_attempt(result, ticket, delay):
            stats['calls'] += 1
            if result.http_status == 429:
                stats['throttled'] += 1
                stats['backoff_seconds'] += delay or 0
            return None

        batch_size = max(1, int(os.getenv('BATCH_SIZE', '10')))
        recognizer = TrackRecognizer(quiet=True, on_attempt=on_attempt,
                                     max_retry_seconds=MAX_RETRY_SECONDS,
                                     continuation_deadline=deadline)
        try:
            while len(done) < len(grid):
                if deadline - time.monotonic() < 1:
                    raise Inconclusive(f'deadline_with_{len(grid) - len(done)}_windows_unresolved')
                if stats['passes']:
                    pause = max(throttle_delay(stats['passes']),
                                recognizer._quota_cooldown_until - time.monotonic())
                    await asyncio.sleep(max(0, min(pause, deadline - time.monotonic() - 1)))
                stats['passes'] += 1
                pending = [w for w in grid if w['index'] not in done]
                for start in range(0, len(pending), batch_size):
                    if time.monotonic() >= deadline:
                        break
                    segments = []
                    for w in pending[start:start + batch_size]:
                        path = work / f'w{w["index"]}.wav'
                        path.write_bytes(base.wav_bytes(window_pcm(w)))
                        segments.append({'file': path, 'index': w['index'],
                                         'timestamp': w['start_frame'] / RATE})
                    with contextlib.redirect_stdout(io.StringIO()):
                        results = await recognizer.recognize_batch(segments, total_segments=len(grid))
                    for segment, result in zip(segments, results):
                        if not result.is_valid or not isinstance(result.raw_data, dict):
                            continue
                        track = result.raw_data.get('track') or {}
                        if result.recognized and not all(str(track.get(k) or '').strip()
                                                         for k in ('key', 'title', 'subtitle')):
                            stats['identity_incomplete'] += 1
                            continue  # retried like any unresolved window
                        done[segment['index']] = reduce_hit(segment['index'], bool(result.recognized),
                                                            result.raw_data)
                base.say(f'pass {stats["passes"]}: {len(done)}/{len(grid)} windows, '
                         f'{stats["throttled"]} throttled so far')
        finally:
            await recognizer.close()
        return [done[w['index']] for w in grid]
    finally:
        for path in work.iterdir():
            path.unlink(missing_ok=True)
        work.rmdir()


# ---------------------------------------------------------------- commands

def load_request() -> tuple[list[str], list[dict]]:
    return validate_request(json.loads(Path('.github/sampling-compare-request.json').read_text()))


def plan() -> int:
    sets, arms = load_request()
    jobs = []
    for sid in sets:
        progress = base.call('yoon_partial_progress', sid)
        if progress is None:
            raise SystemExit('unknown partial family')
        for arm in arms:
            n = len(arm_grid(progress['fragments'], arm))
            if not 1 <= n <= MAX_ARM_WINDOWS:
                raise SystemExit(f'arm {arm["name"]} window count {n} outside 1..{MAX_ARM_WINDOWS}')
            count = math.ceil(n / SHARD_WINDOWS)
            jobs += [{'set': sid, 'arm': arm['name'], 'index': i, 'count': count} for i in range(count)]
            base.say(f'{sid[:8]} {arm["name"]}: {n} windows in {count} shard(s)')
    if len(jobs) > MAX_JOBS:
        raise SystemExit(f'{len(jobs)} shard jobs exceed {MAX_JOBS}')
    Path(os.environ.get('PLAN_OUTPUT', 'plan.json')).write_text(
        json.dumps({'shards': jobs, 'sets': sets}))
    return 0


async def recognize() -> int:
    sets, arms = load_request()
    sid = base.set_id()
    arm = next(a for a in arms if a['name'] == os.environ['SAMPLING_ARM'])
    index, count = int(os.environ['SHARD_INDEX']), int(os.environ['SHARD_COUNT'])
    if sid not in sets or not 0 <= index < count:
        raise SystemExit('shard_bounds')
    progress = base.call('yoon_partial_progress', sid)
    grid = arm_grid(progress['fragments'], arm)
    lo, hi = base.shard_bounds(len(grid), index, count)
    stats = {'calls': 0, 'throttled': 0, 'backoff_seconds': 0.0, 'passes': 0,
             'identity_incomplete': 0}
    started = time.monotonic()
    hits = await recognize_windows(grid[lo:hi], arm_frames(arm)[0], source_links(sid, progress),
                                   stats, started + STUDY_DEADLINE_SECONDS)
    stats['runtime_seconds'] = round(time.monotonic() - started)
    out = Path(os.environ.get('HITS_OUTPUT', 'hits.bin'))
    out.write_bytes(seal({'set': sid, 'arm': arm['name'], 'index': index, 'count': count,
                          'lo': lo, 'hi': hi, 'hits': hits, 'stats': stats}))
    base.say(f'{sid[:8]} {arm["name"]} shard {index + 1}/{count}: {len(hits)} windows, '
             + json.dumps(stats))
    return 0


def combine() -> int:
    sets, arms = load_request()
    sid = base.set_id()
    progress = base.call('yoon_partial_progress', sid)
    grid_a = base.windows(progress['fragments'])
    if len(grid_a) != progress['expected']:
        raise SystemExit('window_grid_mismatch')
    evidence = base.call('yoon_partial_hits_for', sid)
    results = {BASELINE['name']: {**identified(grid_a, evidence['hits'], BASELINE),
                                  'window': 30, 'stride': 15,
                                  'analysed_overlap': analysed_overlap(BASELINE),
                                  'recorded': True}}
    shards: dict[str, list[dict]] = {}
    for blob in sorted(Path(os.environ.get('HITS_DIR', 'hits')).rglob('*.bin')):
        payload = unseal(blob.read_bytes())
        if payload['set'] == sid:
            shards.setdefault(payload['arm'], []).append(payload)
    for arm in arms:
        grid = arm_grid(progress['fragments'], arm)
        parts = sorted(shards.get(arm['name'], []), key=lambda p: p['index'])
        complete = bool(parts) and len(parts) == parts[0]['count'] and (
            [(p['index'], p['lo'], p['hi']) for p in parts]
            == [(i, *base.shard_bounds(len(grid), i, parts[0]['count']))
                for i in range(parts[0]['count'])])
        row = {'window': arm['window'], 'stride': arm['stride'],
               'analysed_overlap': analysed_overlap(arm), 'windows': len(grid)}
        if not complete:
            row['status'] = f'incomplete: {len(parts)} shard result(s)'
        else:
            hits = [h for p in parts for h in p['hits']]
            row.update(identified(grid, hits, arm))
            for key in ('calls', 'throttled', 'identity_incomplete'):
                row[key] = sum(p['stats'][key] for p in parts)
            row['backoff_seconds'] = round(sum(p['stats']['backoff_seconds'] for p in parts))
            row['shard_runtime_max_seconds'] = max(p['stats']['runtime_seconds'] for p in parts)
            row['shard_runtime_sum_seconds'] = sum(p['stats']['runtime_seconds'] for p in parts)
        results[arm['name']] = row
    base.say('RESULT ' + json.dumps({'set': sid[:8], 'arms': results}))
    return 0


def run(argv: list[str]) -> int:
    if argv == ['plan']:
        return plan()
    if argv == ['recognize']:
        try:
            return asyncio.run(recognize())
        except Inconclusive as exc:  # counts only, no private data
            base.say(f'INCONCLUSIVE: {exc}')
            return 4
    if argv == ['combine']:
        return combine()
    raise SystemExit('usage: plan | recognize | combine')


def main(argv: list[str]) -> int:
    base.quiet_process()
    try:
        return run(argv)
    except SystemExit:
        raise
    except BaseException as error:  # Only the class name: messages can carry private data.
        base.say(f'failed: {type(error).__name__}')
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
