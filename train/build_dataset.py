"""
Build Zoha's fine-tuning data (runs on your PC, CPU only, < 1 minute).

    python train\\build_dataset.py                       # uses kaggle\\zoha_teacher_data*.jsonl
    python train\\build_dataset.py --teacher path\\to\\file.jsonl --teacher another.jsonl

Every example is written exactly the way Zoha sees a request at runtime:
  system   = her real (static) instructions, voice or text style
  user     = <context>time + live PC state</context> + what the user said
  tools    = the same tool subset select_tools() would offer (plus any tool the example uses)
  assistant tool calls → tool results → final reply

Sources
  * Kaggle teacher data (Qwen3.5-35B-A3B, Apache-2.0)        – the bulk
  * data/turns.jsonl: your own real turns that went well    – small share, real phrasing
    (turns you complained about, or where the lie guard had to step in, are left out and
     listed in train/review_failed_turns.jsonl instead)
  * anything that also appears in the stress test is removed, so the before/after test stays fair

Output (train/out/):
  zoha_sft_train.jsonl, zoha_sft_val.jsonl   – upload these to Kaggle (Add Data → New Dataset)
  zoha_heldout_test.jsonl                   – the teacher's "test" split, never trained on
  build_stats.json
"""

from __future__ import annotations

import os
import argparse
import datetime as dt
import glob
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zoha.brain import _tool_list, select_tools, system_prompt  # noqa: E402
from zoha.config import Settings  # noqa: E402
import zoha.tools as T  # noqa: E402

OUT = ROOT / "train" / "out"
SEED = 1611

# The live "PC state" Zoha gets with each message (same shape as the engine's awareness text)
AWARE = {
    "none": "Open windows (front first): Visual Studio Code; File Explorer",
    "youtube": "Media: a YouTube video is playing in your browser.\nYour browser (browser_* tools) is open on: YouTube – https://www.youtube.com/watch (video playing)\n"
               "Open windows (front first): Zoha's browser – YouTube; Visual Studio Code",
    "youtube_ad": "Your browser (browser_* tools) is open on: YouTube – https://www.youtube.com/watch (video: an ad is playing, skippable soon)\n"
                  "Open windows (front first): Zoha's browser – YouTube; Visual Studio Code",
    "youtube_paused": "Your browser (browser_* tools) is open on: YouTube – https://www.youtube.com/watch (video paused)\n"
                      "Open windows (front first): Zoha's browser – YouTube; Visual Studio Code",
    "spotify": "Media: a song is playing in Spotify.\nOpen windows (front first): Spotify; Visual Studio Code",
    "page": "Your browser (browser_* tools) is open on: a web page – https://www.amazon.in/s?k=headphones\n"
            "Open windows (front first): Zoha's browser – Amazon.in; Visual Studio Code",
    "notepad": "Open windows (front first): Untitled - Notepad; Visual Studio Code",
}
BROWSER_CTX = {"youtube", "youtube_ad", "youtube_paused", "page"}


NON_LATIN = re.compile(r"[\u0900-\u097F\u0B80-\u0BFF\u0C00-\u0C7F]")
PLACEHOLDER = re.compile(r"\{(?:user|name|username|user_name)\}", re.I)


def clean(r: dict) -> dict | None:
    """Fix the teacher's habits that would teach Zoha wrong things. Returns None to drop the example."""
    r = dict(r)
    reply = str(r.get("reply") or "")
    # "{user}" placeholders → just drop the address ("…paid in full, {user}." → "…paid in full.")
    reply = re.sub(r",?\s*" + PLACEHOLDER.pattern + r"\s*([,.!?])?", lambda m: m.group(1) if m.group(1) and m.group(1) != "," else "", reply, flags=re.I)
    reply = re.sub(r"^\s*(?:hey|hi|hello|ok(?:ay)?|sure)?\s*[,!]\s*", lambda m: m.group(0) if m.group(0).strip(" ,!") else "", reply)
    # invented names used to address the user ("Locked for you, Arjun.") → drop the name, unless the user said it
    m = re.search(r",\s+([A-Z][a-z]{2,})([.!?])\s*$", reply)
    if m and m.group(1).lower() not in str(r.get("user", "")).lower() and m.group(1) != os.getenv("USER_NAME", ""):
        reply = reply[:m.start()] + m.group(2)
    reply = re.sub(r"\s{2,}", " ", reply).strip()
    reply = reply[:1].upper() + reply[1:] if reply else reply
    if not reply:
        return None
    r["reply"] = reply
    # speech arrives in English letters (Whisper is set to English): native-script input is a typed conversation
    if NON_LATIN.search(str(r.get("user", ""))):
        r["modality"] = "text"
    elif NON_LATIN.search(reply) and (r.get("modality") or "voice") == "voice":
        return None  # Latin speech answered in Devanagari – her voice can't read that
    return r


def recovered_from_rejected(paths) -> list:
    """Typed answers the judge dropped only for markdown (it couldn't see they were typed, not spoken)."""
    out = []
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                x = json.loads(line)
            except Exception:
                continue
            why = str(x.get("why", "")).lower()
            ex = x.get("ex") or {}
            if why.startswith("judge") and ("markdown" in why or "bold" in why or "list" in why) and ex.get("modality") == "text" \
                    and not any(k in why for k in ("language", "claim", "missing", "wrong", "should")):
                out.append(ex)
    return out


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9ऀ-ॿ ]+", "", (s or "").lower()).strip()


def context_block(rng: random.Random, ctx: str) -> str:
    t = dt.datetime(2026, rng.randint(1, 12), rng.randint(1, 28), rng.randint(7, 23), rng.choice([0, 5, 12, 20, 34, 41, 55]))
    parts = [f"Now: {t:%A %d %B %Y, %I:%M %p} (local time).",
             'Live state of the PC right now (use it to understand vague requests like "pause it", '
             '"make it full screen", "close that"):\n' + AWARE.get(ctx, AWARE["none"])]
    return "<context>\n" + "\n\n".join(parts) + "\n</context>\n\n"


def call_msg(calls):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"type": "function", "function": {"name": c["name"], "arguments": c.get("arguments") or c.get("args") or {}}}
                           for c in calls]}


def desktop_tools(user: str, hist, ctx: str, used) -> list:
    T.CTX.browser_open_hint = ctx in BROWSER_CTX
    hist_msgs = [m for h in hist for m in ({"role": "user", "text": h.get("user", "")}, {"role": "assistant", "text": h.get("zoha", "")})]
    names = select_tools(user, hist_msgs, set()) | set(used)
    T.CTX.browser_open_hint = None
    return [t for t in _tool_list(names) if t["function"]["name"] in T.REGISTRY]


def core_system(domain: str) -> str:
    return (f"You are Zoha, Zhessor's AI assistant, working inside a {domain} app. You act through the tools you are given: "
            "when the user asks you to do something, call the right tool with exact arguments; never say something is done unless "
            "a tool did it. If a required detail is missing, ask one short question. Small talk gets a friendly reply, no tool. "
            "Replies are short and natural; no emojis.")


def from_teacher(r: dict, rng: random.Random, sys_voice: str, sys_text: str) -> dict | None:
    kind = r.get("kind", "")
    modality = r.get("modality") or "voice"
    calls = r.get("calls") or []
    results = r.get("tool_results") or []
    hist = r.get("history") or []
    ctx = r.get("context") or "none"
    if kind == "core":
        tools_raw = r.get("tools") or []
        tools = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                                   "parameters": t.get("parameters") or {"type": "object", "properties": {}}}}
                 for t in tools_raw if isinstance(t, dict) and t.get("name")]
        system = core_system(r.get("topic", "business"))
        user_prefix = ""
    else:
        tools = desktop_tools(r["user"], hist, ctx, [c["name"] for c in calls])
        system = sys_voice if modality == "voice" else sys_text
        user_prefix = context_block(rng, ctx)
    msgs = [{"role": "system", "content": system}]
    for h in hist:
        if h.get("user") and h.get("zoha"):
            msgs += [{"role": "user", "content": h["user"]}, {"role": "assistant", "content": h["zoha"]}]
    msgs.append({"role": "user", "content": user_prefix + r["user"]})
    if calls:
        if len(results) != len(calls):
            return None
        msgs.append(call_msg(calls))
        for c, res in zip(calls, results):
            msgs.append({"role": "tool", "name": c["name"], "content": str(res)})
    msgs.append({"role": "assistant", "content": r["reply"]})
    return {"messages": msgs, "tools": tools, "meta": {"src": "teacher", "kind": kind, "id": r.get("id"), "lang": r.get("lang", "")}}


def from_journal(r: dict, rng: random.Random, sys_voice: str, sys_text: str) -> dict | None:
    tools_used = r.get("tools") or []
    calls = [{"name": t["name"], "arguments": t.get("args") or {}} for t in tools_used]
    results = [t.get("result", "") for t in tools_used]
    modality = r.get("modality") or "voice"
    ctx = "page" if any(c["name"].startswith("browser_") for c in calls) else "none"
    tools = desktop_tools(r["text"], [], ctx, [c["name"] for c in calls])
    msgs = [{"role": "system", "content": sys_voice if modality == "voice" else sys_text},
            {"role": "user", "content": context_block(rng, ctx) + r["text"]}]
    if calls:
        msgs.append(call_msg(calls))
        for c, res in zip(calls, results):
            msgs.append({"role": "tool", "name": c["name"], "content": str(res)})
    msgs.append({"role": "assistant", "content": r["reply"]})
    return {"messages": msgs, "tools": tools, "meta": {"src": "journal", "id": r.get("id")}}


def round2(progress: str, web_files: list, rng: random.Random):
    """Next training round: the training examples the first run didn't reach (same file, same order as uploaded)
    + clean web pages from the web teacher. Writes train/out/zoha_sft_round2.jsonl and zoha_web_val.jsonl."""
    done = json.loads(Path(progress).read_text(encoding="utf-8"))["examples_done"]
    rows = [json.loads(l) for l in (OUT / "zoha_sft_train.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rest = rows[done:]
    web, seen = [], set()
    for f in web_files:
        for line in Path(f).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            key = (r.get("business"), r.get("area"), len(r.get("page", "")) // 500)
            if not r.get("page") or key in seen or len(r["page"]) > 19000:
                continue
            seen.add(key)
            web.append({"messages": [{"role": "user", "content": r["prompt"]}, {"role": "assistant", "content": r["page"]}],
                        "source": "web_teacher"})
    rng.shuffle(web)
    n_val = min(20, len(web) // 20)
    web_val, web = web[:n_val], web[n_val:]
    out = rest + web
    rng.shuffle(out)
    with open(OUT / "zoha_sft_round2.jsonl", "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(OUT / "zoha_web_val.jsonl", "w", encoding="utf-8") as fh:
        for r in web_val:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"round 2: {len(rest):,} not-yet-learned Zoha examples (skipped the {done:,} learned) + {len(web):,} web pages "
          f"→ zoha_sft_round2.jsonl ({len(out):,}) · web val {len(web_val)}")
    print("Upload zoha_sft_round2.jsonl and zoha_web_val.jsonl as a NEW version of the 'zoha-sft' dataset, plus the first run's "
          "Output (zoha_lora.zip) as an input, then run kaggle\\zoha_train.ipynb.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", action="append", default=[], help="teacher JSONL file(s); default kaggle/zoha_teacher_data*.jsonl")
    ap.add_argument("--journal", default=str(ROOT / "data" / "turns.jsonl"))
    ap.add_argument("--val-share", type=float, default=0.04)
    ap.add_argument("--round2", default="", help="zoha_progress.json from the first training run → build the round-2 file")
    ap.add_argument("--web", action="append", default=[], help="web teacher JSONL(s); default kaggle/**/zoha_web_pages*.jsonl")
    a = ap.parse_args()
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    if a.round2:
        web = a.web or sorted(set(glob.glob(str(ROOT / "kaggle" / "**" / "zoha_web_pages*.jsonl"), recursive=True)))
        return round2(a.round2, web, rng)

    s = Settings()
    sys_voice = system_prompt(s, None, "voice", dynamic=False)
    sys_text = system_prompt(s, None, "text", dynamic=False)

    # stress-test sentences must never be trained on (they are the exam)
    exam = set()
    cases = ROOT / "data" / "stress" / "cases.jsonl"
    if cases.exists():
        for line in cases.read_text(encoding="utf-8").splitlines():
            try:
                exam.add(norm(json.loads(line)["text"]))
            except Exception:
                pass

    files = a.teacher or sorted(set(glob.glob(str(ROOT / "kaggle" / "**" / "zoha_teacher_data*.jsonl"), recursive=True)))
    rejected = sorted(set(glob.glob(str(ROOT / "kaggle" / "**" / "zoha_teacher_rejected*.jsonl"), recursive=True)))
    if a.teacher:
        rejected = [str(Path(f).with_name(Path(f).name.replace("_data", "_rejected"))) for f in a.teacher
                    if Path(f).with_name(Path(f).name.replace("_data", "_rejected")).exists()]
    if not files:
        sys.exit("No teacher data found. Download zoha_teacher_data.jsonl from the Kaggle run's Output into the kaggle folder.")
    stats = Counter()
    train, heldout, seen = [], [], set()
    rescued = recovered_from_rejected(rejected)
    stats["recovered_typed_answers"] = len(rescued)

    def rows():
        for f in files:
            for line in Path(f).read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    yield json.loads(line)
                except Exception:
                    stats["bad_json"] += 1
        yield from rescued

    for r in rows():
        if True:
            r0 = r
            r = clean(r0)
            if r is None:
                stats["dropped_by_cleanup"] += 1
                continue
            if r["reply"] != r0.get("reply"):
                stats["reply_cleaned"] += 1
            if r.get("modality") != r0.get("modality"):
                stats["made_typed"] += 1
            k = norm(r.get("user", ""))
            if not k or k in seen:
                stats["duplicate"] += 1
                continue
            if k in exam:
                stats["in_stress_test"] += 1
                continue
            seen.add(k)
            ex = from_teacher(r, rng, sys_voice, sys_text)
            if not ex:
                stats["malformed"] += 1
                continue
            (heldout if r.get("split") == "test" else train).append(ex)
            stats["teacher_" + ("test" if r.get("split") == "test" else "train")] += 1
            stats["kind_" + r.get("kind", "?")] += 1

    # your own good turns
    jpath = Path(a.journal)
    review = []
    if jpath.exists():
        rows = [json.loads(l) for l in jpath.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        bad = {r["id"] for r in rows if r.get("type") == "feedback" and r.get("bad")}
        for r in rows:
            if r.get("type") == "feedback" or not r.get("text") or not r.get("reply"):
                continue
            good = (r["id"] not in bad and not r.get("flags") and not r.get("interrupted")
                    and str(r.get("route", "")).startswith("brain") and all(t.get("ok", True) for t in r.get("tools", [])))
            if not good:
                if r["id"] in bad or r.get("flags"):
                    review.append(r)
                continue
            k = norm(r["text"])
            if k in seen or k in exam:
                continue
            seen.add(k)
            ex = from_journal(r, rng, sys_voice, sys_text)
            if ex:
                train.append(ex)
                stats["journal"] += 1
    (OUT.parent / "review_failed_turns.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in review) + ("\n" if review else ""),
                                                         encoding="utf-8")
    stats["journal_failed_for_review"] = len(review)

    rng.shuffle(train)
    n_val = max(1, int(len(train) * a.val_share)) if len(train) > 20 else 0
    val, train = train[:n_val], train[n_val:]

    def dump(name, rows):
        with open(OUT / name, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("zoha_sft_train.jsonl", train)
    dump("zoha_sft_val.jsonl", val)
    dump("zoha_heldout_test.jsonl", heldout)
    chars = [len(json.dumps(r, ensure_ascii=False)) for r in train]
    stats.update({"train": len(train), "val": len(val), "heldout_test": len(heldout),
                  "approx_tokens_per_example": int(sum(chars) / max(1, len(chars)) / 3.3)})
    (OUT / "build_stats.json").write_text(json.dumps(dict(stats), indent=1), encoding="utf-8")
    print(f"train {len(train):,} · val {len(val):,} · held-out test {len(heldout):,} · ~{stats['approx_tokens_per_example']:,} tokens each")
    print("details:", dict(stats))
    print(f"\nUpload the files in {OUT} to Kaggle (New Dataset named 'zoha-sft'), then run kaggle\\zoha_train.ipynb.")


if __name__ == "__main__":
    main()
