"""N04 audio-learned-v2b: rebuild the Nov 13 training set, train, validate.

  export    Production DB (read only): entries of the 71 training sets and the
            115 stored v2b Unknown entries -> sealed export.bin, plus the set
            matrix on stdout (GITHUB_OUTPUT format).
  features  one set: download, per-second v2b frame features -> sealed npz.
  train     fold models (fold = SETS.index(sid) % 5, as in learn2.py) to check
            reproduction of the 115 stored entries within 15 s, then one model
            on all sets -> models/boundaries_v2b.joblib, checked the same way.

Logs carry counts only; set data travel only as sealed five-day artifacts.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PREFIXES = """030e88ba 059111f5 05f928d3 06736bd1 07031499 08d8e642 0b45c921 0e57c07a 15dfd2a8 166aa113 1dcc37a6
1fac3656 24725eec 27e09b02 2981627f 2e00b3b8 320c3a8a 3304bbf5 34c24e6f 37556633 3c7f0a6f 3ccb6b49 3cfd3922 3dd97f0d
460120d2 4667b11b 47a80a5c 4e776906 506f30b0 535d081d 5a3f3916 5db3e39b 5db45e36 639e2fca 69a2f1e1 6c31f348 6dfdaf6a
743ba568 74685036 754b2d20 77b6c461 798070da 827bb2af 8325ba13 8ff861c7 905d376d 9c8367ec 9d5efb50 a13fd190 a3db1d62
a4513919 a6bb7383 ac50d7b1 ad9fe081 b2f2ae09 b3d40ab4 b6a462e8 b7b8b7b8 c76d8067 cbc9bda6 d4c5c295 d565c1ff d777d54f
dd1edbaf e12d6e96 e6e80f03 e86d8f86 ea8ab384 ec36536b ed511a43 f807d331""".split()


def _seal(data: bytes) -> bytes:
    from worker.jobs import yoon_sampling_compare as study
    return study._openssl([], data)


def _unseal(data: bytes) -> bytes:
    from worker.jobs import yoon_sampling_compare as study
    return study._openssl(['-d'], data)


def export() -> int:
    from psycopg import connect
    from psycopg.rows import dict_row
    with connect(os.environ['DATABASE_URL_DIRECT'], row_factory=dict_row) as conn, conn.cursor() as cur:
        sets = {}
        for prefix in PREFIXES:
            cur.execute("""select id, source_url, duration_seconds from app.sets
                           where id::text like %s and visibility = 'public'""", (prefix + '%',))
            rows = cur.fetchall()
            if len(rows) == 1:
                sets[str(rows[0]['id'])] = dict(url=rows[0]['source_url'], seconds=rows[0]['duration_seconds'])
        cur.execute("""select distinct set_id from app.set_entries
                       where metadata->>'provisional_boundary_method' = 'audio-learned-v2b'""")
        stored_sets = [str(r['set_id']) for r in cur.fetchall()]
        for sid in stored_sets:
            if sid not in sets:
                cur.execute("select source_url, duration_seconds from app.sets where id = %s", (sid,))
                r = cur.fetchone()
                sets[sid] = dict(url=r['source_url'], seconds=r['duration_seconds'], validation_only=True)
        for sid, item in sets.items():
            cur.execute("""select position, display_title, display_artist, track_id::text as track_id,
                                  start_time_seconds as s, end_time_seconds as e, detection_count as n,
                                  metadata->'provisional_boundaries' as pb,
                                  metadata->>'provisional_boundary_method' as method
                           from app.set_entries where set_id = %s order by position""", (sid,))
            item['entries'] = cur.fetchall()
    stored = sum(1 for i in sets.values() for e in i['entries'] if e['method'] == 'audio-learned-v2b')
    Path(os.environ.get('EXPORT_OUTPUT', 'export.bin')).write_bytes(_seal(json.dumps(sets).encode()))
    print(f'training prefixes matched: {sum(1 for i in sets.values() if not i.get("validation_only"))}/{len(PREFIXES)}; '
          f'stored v2b entries: {stored} in {len(stored_sets)} sets', file=sys.stderr)
    print('sets=' + json.dumps(sorted(sets)))
    return 0


def features() -> int:
    import numpy as np
    import boundaries_v2b as v2b
    from audio_downloader import AudioDownloader
    sid = os.environ['SET_ID']
    item = json.loads(_unseal(Path(os.environ['EXPORT_INPUT']).read_bytes()))[sid]
    work = Path(tempfile.mkdtemp(prefix='n04-'))
    downloader = AudioDownloader()
    downloader.assets_dir = work
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        audio = downloader.download(item['url'], work / 'mix.mp3')
    wav = work / 'mix.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(audio), '-ac', '1', '-ar', '11025', str(wav)], check=True)
    started = time.monotonic()
    F = v2b.frame_features(v2b.audio_features(str(wav)))
    buf = io.BytesIO()
    np.savez_compressed(buf, F=F.astype(np.float32))
    Path(os.environ.get('FEAT_OUTPUT', 'features.bin')).write_bytes(_seal(buf.getvalue()))
    print(f'{sid[:8]}: {F.shape[0]} s x {F.shape[1]} in {round(time.monotonic() - started)} s')
    return 0


def _is_unknown(e) -> bool:
    return e['track_id'] is None and (e['display_title'] or '').strip().lower() == 'unknown track'


def known_boundaries(entries) -> list:
    """learn2.py: consecutive identified entries, both >= 6 detections, gap <= 60 s (pseudo
    rule) or both >= 90 s long (MixesDB tsv rule); item = (prev_start, next_start, next_end)."""
    out = set()
    for a, b in zip(entries, entries[1:]):
        if _is_unknown(a) or _is_unknown(b) or a['e'] is None or b['e'] is None:
            continue
        gap = b['s'] - a['e']
        if gap > 60:
            continue
        if (a['track_id'] and b['track_id'] and a['n'] >= 6 and b['n'] >= 6) or \
                (a['e'] - a['s'] >= 90 and b['e'] - b['s'] >= 90):
            out.add((int(a['s']), int(b['s']), int(b['e'])))
    return sorted(out)


def train() -> int:
    import numpy as np
    import joblib
    import boundaries_v2b as v2b
    data = json.loads(_unseal(Path(os.environ['EXPORT_INPUT']).read_bytes()))
    fdir = Path(os.environ['FEATURES_DIR'])
    F, KB = {}, {}
    for sid, item in data.items():
        p = fdir / f'features-{sid}' / 'features.bin'
        if not p.exists():
            continue
        F[sid] = np.load(io.BytesIO(_unseal(p.read_bytes())))['F']
        # learn2.py trained on the 71 listed sets AND the "pseudo" Production sets
        # (the ones holding the stored v2b entries); held-out by fold.
        KB[sid] = known_boundaries(item['entries'])
    SETS = sorted(s for s in KB if KB[s])
    print(f'features: {len(F)} sets; training sets with known boundaries: {len(SETS)}; '
          f'known boundaries: {sum(len(KB[s]) for s in SETS)}')

    def fit(sids):
        X, y = [], []
        for s in sids:
            a, b = v2b.labelled(F[s], KB[s]); X += a; y += b
        m = v2b.new_model(); m.fit(np.array(X), np.array(y)); return m

    def check(prob_of) -> dict:
        stats = dict(entries=0, boundaries=0, within15=0, count_match=0, missing_audio=0)
        detail = []
        for sid, item in data.items():
            for e in item['entries']:
                if e['method'] != 'audio-learned-v2b':
                    continue
                stats['entries'] += 1
                if sid not in F:
                    stats['missing_audio'] += 1; continue
                want = sorted(int(b['start_seconds']) for b in (e['pb'] or []))
                got = [b['start_seconds'] for b in v2b.predict(prob_of(sid), int(e['s']), int(min(e['e'], len(F[sid]))))]
                stats['boundaries'] += len(want)
                stats['within15'] += sum(1 for w in want if any(abs(w - g) <= 15 for g in got))
                stats['count_match'] += len(want) == len(got)
                detail.append(dict(set=sid, start=e['s'], end=e['e'], want=want, got=got))
        return stats, detail

    folds = {}
    for k in range(5):
        m = fit([s for i, s in enumerate(SETS) if i % 5 != k])
        for i, s in enumerate(SETS):
            if i % 5 == k:
                folds[s] = v2b.probability_curve(m, F[s])
    full = fit(SETS)
    fold_stats, fold_detail = check(lambda s: folds.get(s) if s in folds else v2b.probability_curve(full, F[s]))
    full_stats, full_detail = check(lambda s: v2b.probability_curve(full, F[s]))
    print('fold models vs stored:', json.dumps(fold_stats))
    print('all-sets model vs stored:', json.dumps(full_stats))
    out = Path(os.environ.get('MODEL_OUTPUT', 'models/boundaries_v2b.joblib'))
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(full, out, compress=3)
    Path(os.environ.get('REPORT_OUTPUT', 'report.bin')).write_bytes(_seal(json.dumps(
        dict(fold=fold_stats, full=full_stats, fold_detail=fold_detail, full_detail=full_detail)).encode()))
    print(f'model {out.stat().st_size} bytes')
    return 0


def main(argv: list[str]) -> int:
    return {'export': export, 'features': features, 'train': train}[argv[0]]()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
