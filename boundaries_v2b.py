"""Provisional track boundaries inside Unknown stretches, method audio-learned-v2b (N04).

Ported from the Nov 13 N04 study code (novelty.py, seg.py, framefeat.py,
learn2.py, bench.py, predict_v2b.py). Pipeline:

1. ``audio_features(wav)``: per-second MFCC / chroma / onset-rhythm / RMS from
   11025 Hz mono audio.
2. ``frame_features(f)``: Foote novelty at four kernel lengths per feature
   family, loudness steps, and pre/post similarity, plus local normalisation.
3. A gradient-boosted boundary detector (trained offline on known-to-known
   Shazam boundaries; see ``labelled``) gives a per-second boundary
   probability. ``probability_curve`` smooths it; ``encode_curve`` stores it as
   one byte per second.
4. ``predict(p, s, e)``: for an Unknown span of at least 240 s, a duration-aware
   DP chooses how many tracks it holds and where the extra ones start.

Audio work (1-3) needs numpy, scipy, librosa and scikit-learn; placement (4)
needs only numpy and scipy.
"""
from __future__ import annotations

import base64

import numpy as np

METHOD = 'audio-learned-v2b'
MIN_UNKNOWN_SECONDS = 240
HOP_S = 1.0


# ------------------------------------------------------------------ features

def audio_features(wav: str, sr: int = 11025) -> dict:
    import librosa

    y, sr = librosa.load(wav, sr=sr, mono=True)
    hop = int(sr * 0.25)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop)) ** 2
    mel = librosa.feature.melspectrogram(S=S, sr=sr, n_mels=64)
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(mel), n_mfcc=20)
    chroma = librosa.feature.chroma_stft(S=S, sr=sr)
    onset = librosa.onset.onset_strength(S=librosa.power_to_db(mel), sr=sr, hop_length=hop)
    k = int(HOP_S / 0.25)
    n = mfcc.shape[1] // k
    agg = lambda X: X[:, :n * k].reshape(X.shape[0], n, k).mean(2)  # noqa: E731
    ons = onset[:n * k]
    win = 32  # 8 s of 0.25 s frames
    rhy = np.zeros((48, n))
    for i in range(n):
        a = max(0, i * k - win // 2)
        seg = ons[a:a + win * 2]
        if len(seg) < 8:
            continue
        seg = seg - seg.mean()
        ac = np.correlate(seg, seg, 'full')[len(seg) - 1:len(seg) - 1 + 48]
        if ac[0] > 0:
            rhy[:len(ac), i] = ac / ac[0]
    rms = agg(np.sqrt(S.sum(0, keepdims=True)))
    return dict(mfcc=agg(mfcc), chroma=agg(chroma), rhythm=rhy, rms=rms)


def _z(X):
    X = X - X.mean(1, keepdims=True)
    return X / (X.std(1, keepdims=True) + 1e-8)


def _ssm(X):
    X = X / (np.linalg.norm(X, axis=0, keepdims=True) + 1e-8)
    return X.T @ X


def _foote(S, L):
    n = S.shape[0]
    out = np.zeros(n)
    g = np.exp(-0.5 * ((np.arange(-L, L) + 0.5) / (L / 2)) ** 2)
    sign = np.r_[-np.ones(L), np.ones(L)]
    K = np.outer(g, g) * np.outer(sign, sign)
    Sp = np.pad(S, L, mode='edge')
    for i in range(n):
        out[i] = (Sp[i:i + 2 * L, i:i + 2 * L] * K).sum()
    return out


def novelty(feat: dict, L: int = 30, smooth: int = 4, weights=(1.0, 1.0, 1.0)) -> np.ndarray:
    from scipy.ndimage import uniform_filter1d

    nov = 0.0
    for name, w in zip(('mfcc', 'chroma', 'rhythm'), weights):
        if not w:
            continue
        X = feat[name]
        n = X.shape[1] // 2
        X = X[:, :n * 2].reshape(X.shape[0], n, 2).mean(2)
        X = uniform_filter1d(X, smooth, axis=1)
        nov = nov + w * _foote(_ssm(_z(X)), L // 2)
    nov = np.maximum(nov, 0)
    nov = nov / (np.percentile(nov, 99) + 1e-8)
    return np.repeat(nov, 2)[:feat['mfcc'].shape[1]]


def frame_features(f: dict) -> np.ndarray:
    from scipy.ndimage import median_filter, minimum_filter1d, uniform_filter1d

    n = f['mfcc'].shape[1]
    cols = []
    for L in (30, 60, 120, 180):
        for i in range(3):
            w = [0.0, 0.0, 0.0]
            w[i] = 1.0
            cols.append(novelty(f, L=L, weights=tuple(w)))
    r = np.log(f['rms'][0] + 1e-3)
    m30 = uniform_filter1d(r, 30)
    after = np.r_[m30[15:], np.repeat(m30[-1], 15)]
    before = np.r_[np.repeat(m30[0], 15), m30[:-15]]
    cols.append(after - before)
    cols.append(minimum_filter1d(r, 17) - median_filter(r, 121))
    for k in ('mfcc', 'chroma', 'rhythm'):
        X = f[k]
        X = (X - X.mean(1, keepdims=True)) / (X.std(1, keepdims=True) + 1e-8)
        M = uniform_filter1d(X, 70, axis=1)
        pre = np.concatenate([np.repeat(M[:, :1], 55, 1), M[:, :-55]], 1)
        post = np.concatenate([M[:, 55:], np.repeat(M[:, -1:], 55, 1)], 1)
        cs = (pre * post).sum(0) / (np.linalg.norm(pre, axis=0) * np.linalg.norm(post, axis=0) + 1e-8)
        cols.append(1 - cs)
    cols = [np.pad(c[:n], (0, max(0, n - len(c))), mode='edge') for c in cols]
    F = np.stack(cols, 1).astype(np.float32)
    loc = F[:, :12] / (uniform_filter1d(F[:, :12], 300, axis=0) + 1e-3)
    return np.concatenate([F, loc], 1)


# ------------------------------------------------------------------ detector

def labelled(F: np.ndarray, kb, pos_lo: int = -6, pos_hi: int = 6):
    """Training rows from known boundaries [(prev_start, boundary_start, boundary_end)], seconds."""
    n = len(F)
    X, y = [], []
    for ps, bs, _be in kb:
        for t in range(max(0, bs + pos_lo), min(n, bs + pos_hi + 1), 2):
            X.append(F[t]); y.append(1)
        for t in range(ps + 40, bs - 40, 6):
            if t < n:
                X.append(F[t]); y.append(0)
    return X, y


def new_model():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                          l2_regularization=1.0)


def probability_curve(model, F: np.ndarray) -> np.ndarray:
    from scipy.ndimage import uniform_filter1d
    return uniform_filter1d(model.predict_proba(F)[:, 1], 5)


def encode_curve(p: np.ndarray) -> str:
    q = np.clip(np.round(np.asarray(p) * 255), 0, 255).astype(np.uint8)
    return base64.b64encode(q.tobytes()).decode()


def decode_curve(text: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(text), dtype=np.uint8).astype(np.float64) / 255.0


# ------------------------------------------------------------------ placement

def _lp(L, mu, sigma):
    return -((np.log(L) - np.log(mu)) ** 2) / (2 * sigma ** 2)


def dp_place(score, a, b, n, mu=300.0, sigma=0.45, min_len=90, wdur=1.0):
    from scipy.signal import find_peaks

    D = b - a
    seg = score[a:min(b, len(score))]
    if n < 2:
        return []
    if len(seg) < D - 30:
        return [a + int(D * k / n) for k in range(1, n)]
    cand = [0] + [int(p) for p in find_peaks(seg, distance=10)[0] if min_len <= p <= D - min_len] + [D]
    m = len(cand)
    best = np.full((n + 1, m), -np.inf)
    prev = np.zeros((n + 1, m), int)
    best[0, 0] = 0
    for k in range(1, n + 1):
        for j in range(1, m):
            if k < n and j == m - 1:
                continue
            if k == n and j != m - 1:
                continue
            g = seg[cand[j]] if j < m - 1 else 0.0
            for i in range(j):
                if best[k - 1, i] == -np.inf:
                    continue
                L = cand[j] - cand[i]
                if L < min_len:
                    continue
                v = best[k - 1, i] + g + wdur * _lp(L, mu, sigma)
                if v > best[k, j]:
                    best[k, j] = v
                    prev[k, j] = i
    if best[n, m - 1] == -np.inf:
        return [a + int(D * k / n) for k in range(1, n)]
    out = []
    j = m - 1
    for k in range(n, 1, -1):
        j = prev[k, j]
        out.append(a + cand[j])
    return sorted(out)


def dp_free(score, a, b, mu=300.0, sigma=0.45, min_len=90, wdur=1.0, pen=0.0, nmax=12):
    D = b - a
    best = None
    for n in range(1, min(nmax, max(1, int(D / min_len))) + 1):
        bs = dp_place(score, a, b, n, mu, sigma, min_len, wdur)
        edges = [a] + bs + [b]
        tot = (sum(score[x] for x in bs if x < len(score)) - pen * len(bs)
               + wdur * sum(_lp(max(y - x, 1), mu, sigma) for x, y in zip(edges, edges[1:])))
        if best is None or tot > best[0]:
            best = (tot, bs)
    return best[1]


def predict(p: np.ndarray, s: int, e: int) -> list[dict]:
    """Provisional boundaries for one Unknown span [s, e) in seconds (>= 240 s)."""
    if e - s < MIN_UNKNOWN_SECONDS:
        return []
    bs = dp_free(p, int(s), int(e), wdur=0.15, pen=0.1, mu=270)
    return [dict(start_seconds=int(b), basis='learned_boundary',
                 score=round(float(p[b]) if b < len(p) else 0.0, 3)) for b in bs]
