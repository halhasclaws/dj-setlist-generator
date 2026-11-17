"""Combined false-positive score for clustered setlist entries (D07).

Logistic model fitted on the tuning half of the D07 corpus (58 sets; label =
entry credited to a real track by the set's tracklist or by-ear review).
Features are computed per final entry from the set's recognitions:

  g         offset-agreeing detections of the entry's track inside its span
  n         detection count of the entry
  g == 2 / g <= 3
  bleed     sits inside a stronger neighbour's first or last ~60 s
  other     windows in the entry's span that recognised a different song
  near_dup  a stronger entry has a matching or same-base title
  ctx       the entry's artist appears in another entry of the set
  gap       seconds to the nearest other entry (0 when overlapping)
  intro     median provider offset < 45 s (matched at the very start of the track)
  density   detections per window across the span
  tskew / fskew  largest |timeskew| / |frequencyskew| of the agreeing detections

Entries scoring below Config.FALSE_POSITIVE_SCORE_MIN are dropped.
"""

import difflib
import math
import re
import statistics
import unicodedata
from typing import Optional

WEIGHTS = (
    1.1703128726158316,    # bias
    -0.20855506787426525,  # min(g, 10) / 10
    0.20888893824140364,   # min(n, 20) / 20
    -0.8399244142298212,   # g == 2
    -0.3207984246136101,   # g <= 3
    -0.6240644997801731,   # bleed
    0.14482724118907656,   # min(other, 6) / 6
    -0.6792967735823134,   # near_dup
    0.07432743012784557,   # ctx
    -0.3103894303682171,   # min(gap, 300) / 300
    -0.6803323703667831,   # intro
    0.11251367975034744,   # min(density, 1)
    0.13291803704258554,   # min(tskew * 100, 3) / 3
    -0.5995218913703769,   # min(fskew * 100, 3) / 3
)

_NOISE = re.compile(r'\[[^\]]*\]|\((?:[^)]*(?:mix|edit|remix|version|dub|rework|vip|remaster|original|extended'
                    r'|instrumental|feat|ft)[^)]*)\)', re.I)


def norm(text: Optional[str]) -> str:
    text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()
    text = _NOISE.sub(' ', text)
    text = re.sub(r'\b(feat|ft|featuring|vs|x|and|the)\b\.?', ' ', text)
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return ' '.join(text.split())


def _base_title(title: Optional[str]) -> str:
    return norm(re.sub(r'[\(\[].*?[\)\]]', '', title or '')).strip()


def _sim(x: str, y: str) -> float:
    return difflib.SequenceMatcher(None, x, y).ratio() if x and y else 0.0


def _same_track(artist: str, title: str, other_artist: str, other_title: str) -> bool:
    artist, title = norm(artist), norm(title)
    a, b = norm(other_artist), norm(other_title)
    for first, second in ((a, b), (b, a)):
        t = _sim(title, second)
        if t >= 0.8 or (t >= 0.6 and (title in second or second in title) and len(min(title, second, key=len)) >= 5):
            if _sim(artist, first) >= 0.5 or set(artist.split()) & set(first.split()):
                return True
            if t >= 0.92 and len(title) >= 8:
                return True
    return False


def _match(rec) -> dict:
    matches = (rec.raw_data or {}).get('matches') if isinstance(rec.raw_data, dict) else None
    return matches[0] if isinstance(matches, list) and matches and isinstance(matches[0], dict) else {}


def _offset(rec) -> Optional[float]:
    value = _match(rec).get('offset')
    return float(value) if type(value) in (int, float) else None


def _agreeing(recs: list, tolerance: float) -> list:
    anchored = [(rec.timestamp - off, rec) for rec in recs if (off := _offset(rec)) is not None]
    best: list = []
    for anchor, _ in anchored:
        group = [rec for other, rec in anchored if abs(other - anchor) <= tolerance]
        if len(group) > len(best):
            best = group
    return best


def _skew(recs: list, field: str) -> float:
    values = [abs(v) for rec in recs if type(v := _match(rec).get(field)) in (int, float)]
    return max(values) if values else 0.0


def entry_features(tracks: list, recognitions: list, window_seconds: float, tolerance: float) -> list[dict]:
    """Feature dict per track (same order as tracks)."""
    by_song: dict = {}
    for rec in recognitions:
        by_song.setdefault((rec.artist, rec.track_title), []).append(rec)
    by_index = {rec.segment_index: rec for rec in recognitions}

    groups, regions = [], []
    for track in tracks:
        span = set(range(min(track.segment_indices), max(track.segment_indices) + 1))
        recs = by_song.get((track.artist, track.title), [])
        inside = [rec for rec in recs if rec.segment_index in span] or recs
        group = _agreeing(inside, tolerance) or inside[:1]
        groups.append((span, group))
        regions.append((min(r.timestamp for r in group), max(r.timestamp for r in group) + window_seconds)
                       if group else (track.start_time, track.start_time + window_seconds))

    feats = []
    for k, track in enumerate(tracks):
        span, group = groups[k]
        t0, t1 = regions[k]
        n = track.detection_count
        offsets = [off for rec in group if (off := _offset(rec)) is not None]
        other = sum(1 for i in span if i in by_index
                    and (by_index[i].artist, by_index[i].track_title) != (track.artist, track.title))
        bleed = False
        for j, (a, b) in enumerate(regions):
            if j == k or tracks[j].detection_count <= n:
                continue
            if (t0 >= a - 60 and t1 <= a + 60 + window_seconds) or (t0 >= b - 90 and t1 <= b + 60):
                bleed = True
        gap = min([max(0.0, max(a, t0) - min(b, t1)) for j, (a, b) in enumerate(regions) if j != k] or [9999.0])
        words = set(norm(track.artist).split())
        ctx = bool(words) and any(set(norm(o.artist).split()) & words for j, o in enumerate(tracks) if j != k)
        near_dup = any(o.detection_count > n and (_same_track(track.artist, track.title, o.artist, o.title)
                                                  or _base_title(o.title) == _base_title(track.title))
                       for j, o in enumerate(tracks) if j != k)
        feats.append(dict(g=len(group), n=n, bleed=bleed, other=other, near_dup=near_dup, ctx=ctx, gap=gap,
                          intro=(statistics.median(offsets) if offsets else 0) < 45,
                          density=n / max(1, len(span)),
                          tskew=_skew(group, 'timeskew'), fskew=_skew(group, 'frequencyskew')))
    return feats


def score(f: dict) -> float:
    x = (1.0, min(f['g'], 10) / 10, min(f['n'], 20) / 20, float(f['g'] == 2), float(f['g'] <= 3),
         float(f['bleed']), min(f['other'], 6) / 6, float(f['near_dup']), float(f['ctx']),
         min(f['gap'], 300) / 300, float(f['intro']), min(f['density'], 1.0),
         min(f['tskew'] * 100, 3) / 3, min(f['fskew'] * 100, 3) / 3)
    return 1 / (1 + math.exp(-sum(w * v for w, v in zip(WEIGHTS, x))))
