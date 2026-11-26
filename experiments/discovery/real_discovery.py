#!/usr/bin/env python3
"""Run the real discovery search code (queries, filter, dedupe) for the test artists.

Search only: no database, no queue. Writes results/real-<stamp>.json so the AI
review can be run on exactly what discovery would hand it.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

import dj_set_discovery as d  # noqa: E402


def discover(artist: dict) -> dict:
    names = d._unique_search_names([artist["name"], *artist.get("aliases", [])])
    queries = d._build_search_queries(names)
    t0 = time.time()
    seen, raw, empty = set(), [], 0
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for entries in pool.map(d._search_yt_dlp, queries):
            empty += not entries
            for e in entries:
                if e.get("id") and e["id"] not in seen:
                    seen.add(e["id"])
                    raw.append(e)
    sets = d._deduplicate_near_duplicates(d._filter_and_map(raw, names), names)
    return {"artist": artist["name"], "names": names, "queries": len(queries), "empty_queries": empty,
            "raw": len(raw), "secs": round(time.time() - t0), "sets": [asdict(s) for s in sets]}


def main() -> int:
    config = json.loads((HERE / os.environ.get("DISCOVERY_CONFIG", "config.json")).read_text())
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        out = list(pool.map(discover, config["artists"]))
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"real-{stamp}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    for a in out:
        print(a["artist"], "queries", a["queries"], "empty", a["empty_queries"], "raw", a["raw"], "sets", len(a["sets"]), "secs", a["secs"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
