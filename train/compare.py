"""
Old Zoha vs fine-tuned Zoha — same unseen cases, AI only (no parser), one clear report.

    python train\\compare.py --new zoha-ft-4b                 # old = the model in Zoha's settings
    python train\\compare.py --new zoha-ft-4b --per-cat 20    # quicker (fewer cases)

Cases
  * the stress test, a fixed sample of every category (the exam – never trained on)
  * the teacher's held-out "test" split (train/out/zoha_heldout_test.jsonl), Zoha-desktop examples only
Both models get exactly the same cases. Your GPU runs each model in turn (~30–45 min per model at the
default size); it's the same load as the stress test – quit Zoha first.

Writes data/stress/compare_<old>_vs_<new>.md with a verdict:
  switch only if the new model is clearly better overall AND no category got clearly worse.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "stress"


def stress_sample(per_cat: int) -> list:
    cases_path = OUT / "cases.jsonl"
    if not cases_path.exists():
        from stress.cases import write
        write(cases_path)
    by = defaultdict(list)
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            by[c["cat"]].append(c)
    rng = random.Random(2026)
    out = []
    for cat in sorted(by):
        out += rng.sample(by[cat], min(per_cat, len(by[cat])))
    return out


def heldout_cases(limit: int) -> list:
    p = ROOT / "train" / "out" / "zoha_heldout_test.jsonl"
    if not p.exists():
        return []
    out = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
        r = json.loads(line)
        if r["meta"].get("kind") == "core":
            continue  # invented business tools – not Zoha's desktop tools
        msgs = r["messages"]
        last_user = max(i for i, m in enumerate(msgs) if m["role"] == "user" and not str(m["content"]).startswith("<tool"))
        u = msgs[last_user]["content"]
        text = u.split("</context>")[-1].strip()
        hist, prev = [], None
        for m in msgs[1:last_user]:
            if m["role"] == "user":
                prev = m["content"]
            elif m["role"] == "assistant" and prev and m.get("content"):
                hist.append([prev, m["content"]])
                prev = None
        calls = [tc["function"]["name"] for m in msgs[last_user + 1:] for tc in (m.get("tool_calls") or [])]
        ctx = {}
        if "Your browser (browser_* tools) is open" in u:
            ctx = {"browser_open": True, "page": "YouTube" if "YouTube" in u else "a web page",
                   "browser_url": "https://www.youtube.com/watch" if "YouTube" in u else "https://www.amazon.in/s?k=headphones"}
            if "video" in u:
                ctx["video"] = "paused" if "paused" in u else "playing"
        elif "Spotify" in u:
            ctx = {"media": "Spotify: a song (playing)"}
        expect = ({"all": [{"tools": [n], "args": {}} for n in dict.fromkeys(calls)]} if calls
                  else {"none": True, "allow": ["remember"]})
        out.append({"id": f"h{i:05d}", "cat": "heldout:" + (r["meta"].get("kind") or "?"), "text": text, "ctx": ctx,
                    "hist": hist, "expect": expect, "split": "test"})
        if len(out) >= limit:
            break
    return out


def safe(m: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", m)


def run(model: str, cases_file: Path) -> list:
    name = f"compare_{safe(model)}.jsonl"
    print(f"\n=== {model} ===")
    subprocess.run([sys.executable, str(ROOT / "stress_test.py"), "--model", model, "--cases-file", str(cases_file),
                    "--results-name", name], check=True)
    ids = {json.loads(l)["id"] for l in cases_file.read_text(encoding="utf-8").splitlines() if l.strip()}
    rows = {}
    for l in (OUT / name).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("model") == model and r["id"] in ids:
            rows[r["id"]] = r
    return list(rows.values())


def summarise(rows):
    cat = defaultdict(lambda: [0, 0])
    fake = sum(1 for r in rows if r.get("reason") == "fake_done" or "model_claimed" in (r.get("flags") or []))
    for r in rows:
        group = "held-out (teacher test)" if r["cat"].startswith("heldout:") else r["cat"]
        cat[group][0] += r["ok"]
        cat[group][1] += 1
    ok = sum(r["ok"] for r in rows)
    secs = sorted(r.get("secs", 0) for r in rows)
    return {"ok": ok, "n": len(rows), "cat": dict(cat), "fake": fake, "median_s": secs[len(secs) // 2] if secs else 0}


def main():
    from zoha.config import Settings

    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True, help="the fine-tuned Ollama model, e.g. zoha-ft-4b")
    ap.add_argument("--old", default="", help="default: the model in Zoha's settings")
    ap.add_argument("--per-cat", type=int, default=30, help="stress cases per category (default 30 → ~630)")
    ap.add_argument("--heldout", type=int, default=300)
    a = ap.parse_args()
    s = Settings()
    old = a.old or s.local_llm_model
    try:
        import urllib.request
        root = s.local_llm_url.rstrip("/")
        root = root[:-3] if root.endswith("/v1") else root
        names = {m["name"] for m in json.loads(urllib.request.urlopen(root + "/api/tags", timeout=5).read()).get("models", [])}
        for m in (old, a.new):
            if m not in names and m + ":latest" not in names:
                sys.exit(f"'{m}' isn't in Ollama yet. " + ("Run: python train\\install_model.py <folder with the gguf>" if m == a.new else ""))
    except urllib.error.URLError:
        sys.exit("Ollama isn't running – start Zoha once (or run 'ollama serve'), then try again.")
    cases = stress_sample(a.per_cat) + heldout_cases(a.heldout)
    cf = OUT / "compare_cases.jsonl"
    OUT.mkdir(parents=True, exist_ok=True)
    cf.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")
    print(f"{len(cases):,} cases ({sum(1 for c in cases if c['cat'].startswith('heldout'))} held-out) – each model answers all of them")

    A, B = summarise(run(old, cf)), summarise(run(a.new, cf))
    pct = lambda o, n: 100 * o / max(1, n)
    L = [f"# Old vs fine-tuned Zoha (AI only)\n", f"Same {A['n']:,} unseen cases for both.\n",
         "| | Old: " + old + " | New: " + a.new + " |", "|---|---|---|",
         f"| **Correct overall** | {pct(A['ok'], A['n']):.1f}% | **{pct(B['ok'], B['n']):.1f}%** |",
         f"| Fake 'done' (caught by the lie guard) | {A['fake']} | {B['fake']} |",
         f"| Median time per case | {A['median_s']:.1f}s | {B['median_s']:.1f}s |", "",
         "| Category | Old | New | Change | Cases |", "|---|---|---|---|---|"]
    worse = []
    for c in sorted(set(A["cat"]) | set(B["cat"])):
        ao, an = A["cat"].get(c, [0, 0])
        bo, bn = B["cat"].get(c, [0, 0])
        d = pct(bo, bn) - pct(ao, an)
        if d <= -10 and bn >= 15:
            worse.append(c)
        L.append(f"| {c} | {pct(ao, an):.0f}% | {pct(bo, bn):.0f}% | {'+' if d >= 0 else ''}{d:.0f} | {bn} |")
    better = pct(B["ok"], B["n"]) - pct(A["ok"], A["n"])
    verdict = ("**Switch** – clearly better overall, nothing clearly worse." if better >= 2 and not worse else
               f"**Don't switch yet** – {'better overall but worse at: ' + ', '.join(worse) if worse else 'not clearly better (' + format(better, '+.1f') + ' points)'}.")
    L += ["", "## Verdict", verdict]
    report = OUT / f"compare_{safe(old)}_vs_{safe(a.new)}.md"
    report.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n" + "\n".join(L[:7]) + f"\n\n{verdict}\nReport: {report}")


if __name__ == "__main__":
    main()
