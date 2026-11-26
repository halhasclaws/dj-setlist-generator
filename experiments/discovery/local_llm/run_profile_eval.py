"""Local model writes the artist profile from search results (no web), then judges the backtest sets.

Same prompts as discovery_review.build_profile (web off) and discovery_review.review.
"""
import json, os, time, urllib.request
import run_eval as R

HERE = os.path.dirname(os.path.abspath(__file__))
PSCHEMA = {"type": "object", "properties": {
    "profile": {"type": "string"}, "aliases": {"type": "array", "items": {"type": "string"}},
    "home_signals": {"type": "array", "items": {"type": "string"}},
    "namesakes": {"type": "array", "items": {"type": "string"}}},
    "required": ["profile", "aliases", "home_signals", "namesakes"]}


def chat(prompt, schema, max_tokens=1500):
    body = {"messages": [{"role": "system", "content": R.SYSTEM}, {"role": "user", "content": prompt}],
            "temperature": 0, "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": "p", "schema": schema}}}
    req = urllib.request.Request(R.URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(json.load(r)["choices"][0]["message"]["content"])


def build_profile(artist, aliases, cands):
    names = ", ".join([artist, *aliases])
    sample = "\n".join(R.line(i, c) for i, c in enumerate(cands))
    prompt = (
        f"Someone added the name {names} to an archive of recorded DJ sets by electronic music artists. "
        "Below are long recordings found by searching that name (title, channel, length, year, site).\n"
        f"<candidates>\n{sample}\n</candidates>\n\n"
        "Work out which person the archive means: the electronic DJ or producer behind the largest coherent group "
        "of these recordings (same scene, radio stations, clubs, labels, collaborators, city).\nReturn:\n"
        "- profile: 2 to 4 sentences stating who they are, genre, scenes and cities they play in. State facts only; "
        "do not write doubts like 'could not confirm'.\n"
        "- aliases: other names they perform under (not collaborators).\n"
        "- home_signals: channels, radio stations, show names, clubs, labels and collaborators from the recordings "
        "that belong to this artist.\n"
        "- namesakes: other people with the name, each with what tells them apart (genre, country, job).")
    d = chat(prompt, PSCHEMA)
    return (d["profile"] + "\nPerforms as: " + ", ".join(dict.fromkeys([artist, *aliases, *d.get("aliases", [])]))
            + "\nTheir channels, stations, shows, clubs, labels, collaborators: " + "; ".join(d.get("home_signals", []))
            + "\nOther people with the name (not this artist): " + "; ".join(d.get("namesakes", [])))


def main():
    data = json.load(open(os.path.join(HERE, "data.json")))
    cands = json.load(open(os.path.join(HERE, "candidates.json")))
    artists = sorted(data["profiles"])[R.SHARD::R.SHARDS]
    res, timings, profiles = {}, [], {}
    for a in artists:
        t0 = time.time()
        try:
            prof = build_profile(a, data["aliases"].get(a, []), cands.get(a, []))
        except Exception as e:
            print("PROFILE FAIL", a, str(e)[:200], flush=True); prof = f"Performs as: {a}"
        profiles[a] = prof
        timings.append({"profile": a, "sec": round(time.time() - t0, 1)})
        print("profile", a, f"{time.time() - t0:.0f}s", flush=True)
        items = [x for x in data["items"] if x["a"] == a]
        for s in range(0, len(items), R.BATCH):
            chunk = items[s:s + R.BATCH]
            rows = "\n".join(R.line(s + k, c) for k, c in enumerate(chunk))
            t0 = time.time()
            try:
                vs, usage = R.ask(a, prof, rows)
            except Exception as e:
                print("FAIL", a, s, str(e)[:200], flush=True); vs, usage = [], {}
            timings.append({"n": len(chunk), "sec": round(time.time() - t0, 1), "usage": usage})
            by = {v.get("i"): v for v in vs}
            for k, c in enumerate(chunk):
                v = by.get(s + k) or {"verdict": "unsure", "kind": "other", "reason": "missing"}
                res[c["id"]] = {"v": v.get("verdict"), "kind": v.get("kind"), "reason": v.get("reason")}
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump({"model": R.MODEL, "shard": R.SHARD, "profiles": profiles, "verdicts": res, "timings": timings},
              open(os.path.join(HERE, "results", f"profile-{R.PROMPT}-{R.MODEL}-{R.SHARD}.json"), "w"), indent=0)


if __name__ == "__main__":
    main()
