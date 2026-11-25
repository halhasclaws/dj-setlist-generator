#!/usr/bin/env python3
"""Search-only discovery experiment.

Runs several search strategies for a list of artists and writes every raw
candidate (no filtering) to a TSV, tagged with the strategy and query that
found it, so filters and strategy mixes can be scored offline against known
good and known wrong sets. Touches no database and queues nothing.
"""
from __future__ import annotations

import ast
import concurrent.futures as cf
import csv
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
YT_PROXY = os.environ.get("YT_PROXY", "")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def load_current_terms() -> tuple[list[str], list[str]]:
    """Read _GENERIC_TERMS and _CHANNELS from dj_set_discovery.py without importing it."""
    tree = ast.parse((ROOT / "dj_set_discovery.py").read_text())
    found: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("_GENERIC_TERMS", "_CHANNELS"):
                found[node.targets[0].id] = ast.literal_eval(node.value)
    return found["_GENERIC_TERMS"], found["_CHANNELS"]


def norm(text: str) -> str:
    text = re.sub(r"[_\-.]", " ", text or "")
    return re.sub(r"\s+", " ", text).strip().lower()


def ytdlp(target: str, limit: int | None = None, proxy: str = "") -> tuple[list[dict], str]:
    cmd = ["yt-dlp", "--dump-json", "--flat-playlist", "--no-download", "--no-warnings", "--ignore-errors"]
    if limit:
        cmd += ["--playlist-end", str(limit)]
    if proxy:
        cmd += ["--proxy", proxy]
    cmd.append(target)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return [], "timeout"
    out = []
    for line in res.stdout.splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    err = "" if res.returncode == 0 else (res.stderr.strip().splitlines() or ["rc=%d" % res.returncode])[-1][:300]
    return out, err


def http_json(url: str) -> tuple[dict | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8")), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"[:300]


def row_from_ytdlp(e: dict) -> dict:
    url = e.get("webpage_url") or e.get("url") or ""
    if url and not url.startswith("http") and e.get("ie_key") == "Youtube":
        url = f"https://www.youtube.com/watch?v={url}"
    return {
        "platform": "youtube" if "youtu" in url else ("soundcloud" if "soundcloud" in url else (e.get("ie_key") or "")),
        "url": url,
        "id": e.get("id") or "",
        "title": e.get("title") or "",
        "channel": e.get("channel") or e.get("playlist_uploader") or "",
        "uploader": e.get("uploader") or "",
        "uploader_url": e.get("uploader_url") or e.get("channel_url") or "",
        "duration": e.get("duration") if e.get("duration") is not None else "",
        "upload_date": e.get("upload_date") or e.get("timestamp") or "",
    }


class Run:
    def __init__(self, config: dict):
        self.config = config
        self.generic, self.channels = load_current_terms()
        self.rows: list[dict] = []
        self.log: list[dict] = []

    def add(self, artist: str, strategy: str, query: str, rows: list[dict], err: str, secs: float):
        for r in rows:
            r.update({"artist": artist, "strategy": strategy, "query": query})
            self.rows.append(r)
        self.log.append({"artist": artist, "strategy": strategy, "query": query, "n": len(rows), "err": err, "secs": round(secs, 1)})

    def yt_task(self, artist, strategy, target, limit=None):
        t0 = time.time()
        proxy = YT_PROXY if ("ytsearch" in target or "youtube.com" in target) else ""
        entries, err = ytdlp(target, limit, proxy)
        return artist, strategy, target, [row_from_ytdlp(e) for e in entries], err, time.time() - t0

    def plan(self, a: dict) -> list[tuple]:
        name, aliases = a["name"], a.get("aliases", [])
        strategies = set(self.config["strategies"])
        tasks = []
        terms = self.generic + self.channels
        if "base" in strategies:
            # The current production query set: primary name only here; aliases are the "alias" strategy.
            for t in terms:
                q = f'"{name}" {t}'
                tasks += [(name, "base", f"ytsearch20:{q}"), (name, "base", f"scsearch20:{q}")]
        if "deep" in strategies:
            tasks += [(name, "deep", f'ytsearch100:"{name}"'), (name, "deep", f'scsearch100:"{name}"')]
            for t in ["DJ set", "mix", "live"]:
                tasks += [(name, "deep", f'ytsearch60:"{name}" {t}'), (name, "deep", f'scsearch60:"{name}" {t}')]
        if "alias" in strategies:
            for al in aliases:
                tasks += [(name, "alias", f'ytsearch60:"{al}"'), (name, "alias", f'scsearch60:"{al}"')]
                for t in ["DJ set", "mix", "live"]:
                    tasks += [(name, "alias", f'ytsearch20:"{al}" {t}'), (name, "alias", f'scsearch20:"{al}" {t}')]
        if "sc_user" in strategies:
            for u in a.get("sc_users", []):
                tasks.append((name, "sc_user", f"https://soundcloud.com/{u}/tracks", 500))
        return tasks

    def mixcloud(self, a: dict):
        name = a["name"]
        for q in [name] + a.get("aliases", []):
            url = "https://api.mixcloud.com/search/?" + urllib.parse.urlencode({"q": q, "type": "cloudcast", "limit": 100})
            pages = 0
            t0 = time.time()
            got, err = [], ""
            while url and pages < 3:
                data, err = http_json(url)
                if not data:
                    break
                for c in data.get("data", []):
                    got.append({
                        "platform": "mixcloud",
                        "url": c.get("url", ""),
                        "id": c.get("key", ""),
                        "title": c.get("name", ""),
                        "channel": (c.get("user") or {}).get("name", ""),
                        "uploader": (c.get("user") or {}).get("username", ""),
                        "uploader_url": (c.get("user") or {}).get("url", ""),
                        "duration": c.get("audio_length", ""),
                        "upload_date": (c.get("created_time") or "")[:10],
                    })
                url = (data.get("paging") or {}).get("next")
                pages += 1
            self.add(name, "mixcloud", f"mixcloud:{q}", got, err, time.time() - t0)

    def nts(self, a: dict):
        name = a["name"]
        for q in [name] + a.get("aliases", []):
            t0 = time.time()
            got, err = [], ""
            for offset in (0, 60, 120):
                url = "https://www.nts.live/api/v2/search?" + urllib.parse.urlencode(
                    {"q": q, "version": 2, "offset": offset, "limit": 60, "types[]": "episode"})
                data, err = http_json(url)
                if not data:
                    break
                results = data.get("results") or data.get("data") or []
                if offset == 0 and not results:
                    err = "no results; keys=" + ",".join(sorted(data.keys()))[:200]
                for r in results:
                    art = r.get("article") or {}
                    path = art.get("path") or r.get("path") or ""
                    got.append({
                        "platform": "nts",
                        "url": ("https://www.nts.live" + path) if path.startswith("/") else path,
                        "id": path,
                        "title": r.get("title", ""),
                        "channel": "NTS",
                        "uploader": "NTS",
                        "uploader_url": "",
                        "duration": "",
                        "upload_date": r.get("local_date", ""),
                    })
                if len(results) < 60:
                    break
            self.add(name, "nts", f"nts:{q}", got, err, time.time() - t0)

    def own_auto(self, a: dict, pool: cf.ThreadPoolExecutor):
        """Find the artist's own SoundCloud / YouTube account from search results and list its uploads."""
        name = a["name"]
        names = {norm(n) for n in [name] + a.get("aliases", [])}
        names |= {n.replace(" ", "") for n in names}
        accounts: dict[str, str] = {}
        for r in self.rows:
            if r["artist"] != name or r["strategy"] not in ("base", "deep"):
                continue
            who = {norm(r["uploader"]), norm(r["channel"]), norm(r["uploader"]).replace(" ", "")}
            if who & names and r["uploader_url"]:
                accounts[r["uploader_url"].rstrip("/")] = r["platform"]
        targets = []
        for acc, plat in sorted(accounts.items()):
            if plat == "soundcloud":
                targets.append((name, "own_auto", acc + "/tracks", 500))
            elif plat == "youtube":
                targets.append((name, "own_auto", acc + "/videos", 300))
                targets.append((name, "own_auto", acc + "/streams", 100))
        self.log.append({"artist": name, "strategy": "own_auto", "query": "accounts", "n": len(accounts),
                         "err": "", "secs": 0, "accounts": sorted(accounts)})
        for fut in cf.as_completed([pool.submit(self.yt_task, *t) for t in targets]):
            self.add(*fut.result())

    def go(self):
        strategies = set(self.config["strategies"])
        only = os.environ.get("ONLY_ARTISTS", "").strip()
        artists = [a for a in self.config["artists"] if not only or a["name"] in only.split("|")]
        with cf.ThreadPoolExecutor(max_workers=int(os.environ.get("WORKERS", "6"))) as pool:
            futs = [pool.submit(self.yt_task, *t) for a in artists for t in self.plan(a)]
            for i, fut in enumerate(cf.as_completed(futs), 1):
                self.add(*fut.result())
                if i % 25 == 0:
                    print(f"{i}/{len(futs)} queries done", flush=True)
            for a in artists:
                if "own_auto" in strategies:
                    self.own_auto(a, pool)
                if "mixcloud" in strategies:
                    self.mixcloud(a)
                if "nts" in strategies:
                    self.nts(a)


def main() -> int:
    config = json.loads((HERE / "config.json").read_text())
    run = Run(config)
    t0 = time.time()
    run.go()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    cols = ["artist", "strategy", "query", "platform", "url", "id", "title", "channel", "uploader",
            "uploader_url", "duration", "upload_date"]
    with open(out_dir / f"{stamp}.tsv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in run.rows:
            w.writerow({k: str(r.get(k, "")).replace("\t", " ").replace("\n", " ") for k in cols})
    summary = {"stamp": stamp, "secs": round(time.time() - t0), "rows": len(run.rows),
               "yt_proxy": bool(YT_PROXY), "log": run.log}
    (out_dir / f"{stamp}.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    errs = [l for l in run.log if l["err"]]
    print(f"rows={len(run.rows)} queries={len(run.log)} errors={len(errs)} secs={summary['secs']}")
    for l in errs[:20]:
        print("ERR", l["strategy"], l["query"], l["err"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
