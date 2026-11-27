#!/usr/bin/env python3
"""
Zoha brain bake-off — which local model should run Zoha?

    python bakeoff.py                 # all candidates (downloads what's missing via Ollama)
    python bakeoff.py --models qwen3:4b-instruct nemotron-3-nano:4b
    python bakeoff.py --no-whisper    # don't reserve GPU memory for speech recognition

Close Zoha first. The test keeps Whisper loaded on the GPU (like real use) so speed
numbers are honest. Nothing is actually executed on your PC: tool calls are only
checked, never run.

Scores each model on ~40 real commands from Zoha's logs:
  right action · right details · no fake "done" · no tool calls written as text · speed
Results: data/bakeoff.md (table) and data/bakeoff.json (everything).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zoha import tools as T  # noqa: E402
from zoha.brain import ACTION_RX, CLAIM_RX, _short, parse_text_calls, select_tools, system_prompt  # noqa: E402
from zoha.config import DATA_DIR, load_settings  # noqa: E402
from zoha.local_llm import _root, installed_models, server_up, start_server, find_ollama  # noqa: E402

CANDIDATES = ["qwen3:4b-instruct", "qwen3:8b", "nemotron-3.5-bolt:e4b", "nemotron-3-nano:4b"]

has = lambda k, *subs: lambda a: any(s in str(a.get(k, "")).lower() for s in subs)
eq = lambda k, *vals: lambda a: str(a.get(k, "")).lower() in vals
num = lambda k, v: lambda a: _f(a.get(k)) == v
_f = lambda x: (float(x) if str(x).replace(".", "", 1).isdigit() else None)

# (what you say, acceptable tools [None = plain answer, no tool], argument check, category)
CASES = [
    ("What's the weather in Mumbai today?", ["get_weather"], has("city", "mumbai"), "info"),
    ("Can you play Perfect by Ed Sheeran?", ["play_youtube"], has("query", "perfect"), "media"),
    ("Music over YouTube. Name Perfect by Ed Sheeran.", ["play_youtube"], has("query", "perfect"), "media"),
    ("Stop the song playing over the YouTube.", ["media_control", "browser_video"], eq("action", "pause", "stop"), "media"),
    ("Pause the video over the YouTube.", ["media_control", "browser_video"], eq("action", "pause", "stop"), "media"),
    ("The video isn't stopped.", ["media_control", "browser_video"], eq("action", "pause", "stop", "status"), "media"),
    ("next song", ["media_control", "browser_video"], eq("action", "next"), "media"),
    ("what song is playing right now?", ["media_control", "browser_video"], eq("action", "status"), "media"),
    ("Make the video full screen.", ["browser_video"], eq("action", "fullscreen"), "browser"),
    ("skip the ad", ["browser_video"], eq("action", "skip_ad"), "browser"),
    ("Can you close the Chrome?", ["close_app"], has("name", "chrome"), "apps"),
    ("open the calculator for me", ["open_app"], has("name", "calc"), "apps"),
    ("Zoha, can you open the calculator for me?", ["open_app"], has("name", "calc"), "apps"),
    ("open VS Code and play some lofi", ["open_app", "play_youtube"], None, "apps"),
    ("Start YouTube.", ["open_website", "open_app", "browser_open"], lambda a: "youtube" in json.dumps(a).lower(), "apps"),
    ("open my downloads folder", ["open_folder"], has("folder", "download"), "apps"),
    ("find my resume and open it", ["find_files"], has("query", "resume"), "apps"),
    ("Open the month of December on the Google Calendar.", ["browser_open", "open_website"],
     lambda a: "calendar" in json.dumps(a).lower(), "browser"),
    ("go to amazon and find a laptop stand under 1500 rupees", ["browser_open"], lambda a: "amazon" in json.dumps(a).lower(), "browser"),
    ("search for laptop stands in the browser", ["browser_open"], lambda a: "laptop" in json.dumps(a).lower(), "browser"),
    ("close the browser", ["browser_close"], None, "browser"),
    ("go back to the previous page", ["browser_nav"], eq("action", "back"), "browser"),
    ("set a timer for 25 minutes for focus", ["set_timer"], num("minutes", 25.0), "pc"),
    ("remind me to call Harshil at 6 PM", ["set_reminder"], lambda a: "18:00" in str(a.get("at_time", "")) and "harshil" in str(a.get("message", "")).lower(), "pc"),
    ("take a screenshot", ["take_screenshot"], None, "pc"),
    ("turn the volume down a bit", ["set_volume"], eq("change", "down"), "pc"),
    ("set volume to 30 percent", ["set_volume"], num("level", 30.0), "pc"),
    ("how's my PC doing?", ["system_status"], None, "pc"),
    ("lock my computer", ["lock_pc"], None, "pc"),
    ("make a note: follow up with Harshil about the website launch", ["create_note"], has("text", "harshil"), "pc"),
    ("copy hello world to my clipboard", ["clipboard"], eq("action", "write"), "pc"),
    ("remember that my sister's birthday is on 12 March", ["remember"], has("fact", "12 march", "march 12"), "memory"),
    ("what's the latest news in AI?", ["news_headlines", "web_lookup"], None, "info"),
    ("who won the most recent cricket world cup final?", ["web_lookup", "news_headlines"], None, "info"),
    ("shut down the PC", ["power", None], lambda a: not a.get("confirmed"), "safety"),
    ("Explain what a webhook is in two sentences.", [None], None, "chat"),
    ("How are you doing today?", [None], None, "chat"),
    ("What can you do?", [None], None, "chat"),
    ("Write a two-line poem about Mumbai rain.", [None], None, "chat"),
    ("That's all for today. You can sleep.", [None], None, "chat"),
]


def post_stream(url, body, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            line = line.strip()
            if line:
                yield json.loads(line)


def get_json(url, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def ensure_model(root, model):
    if any(m == model or m == model + ":latest" for m in installed_models(root + "/v1")):
        return True
    print(f"  downloading {model} …", flush=True)
    last = -1
    for ev in post_stream(root + "/api/pull", {"model": model}, timeout=7200):
        if ev.get("error"):
            print(f"  ✗ {ev['error']}")
            return False
        if ev.get("total") and ev.get("completed"):
            pct = int(ev["completed"] * 100 / ev["total"])
            if pct // 10 != last:
                last = pct // 10
                print(f"    {pct}% of {ev['total'] / 1e9:.1f} GB", flush=True)
    return True


def run_case(root, model, settings, text, think_flag, num_ctx):
    names = select_tools(text, [], set())
    tools = [{"type": "function", "function": {**t, "description": _short(t["description"])}} for t in T.schemas() if t["name"] in names]
    msgs = [{"role": "system", "content": system_prompt(settings, None, "voice")}, {"role": "user", "content": text}]
    body = {"model": model, "messages": msgs, "stream": True, "keep_alive": "10m", "tools": tools,
            "options": {"temperature": 0.5, "num_ctx": num_ctx, "num_predict": 450}}
    if think_flag is not None:
        body["think"] = think_flag
    t0 = time.time()
    first, content, thinking, calls, final = None, "", "", [], {}
    for ev in post_stream(root + "/api/chat", body):
        if ev.get("error"):
            raise RuntimeError(ev["error"])
        m = ev.get("message") or {}
        if m.get("thinking"):
            thinking += m["thinking"]
        if m.get("content"):
            if first is None:
                first = time.time() - t0
            content += m["content"]
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            a = fn.get("arguments") or {}
            if isinstance(a, str):
                try:
                    a = json.loads(a)
                except Exception:
                    a = {}
            calls.append({"name": fn.get("name"), "args": a})
            if first is None:
                first = time.time() - t0
        if ev.get("done"):
            final = ev
    total = time.time() - t0
    visible = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    return {
        "calls": calls, "text": visible, "thinking_chars": len(thinking) + (len(content) - len(visible)),
        "written_calls": parse_text_calls(visible) if not calls else [],
        "first_s": round(first if first is not None else total, 2), "total_s": round(total, 2),
        "prompt_tokens": final.get("prompt_eval_count"), "out_tokens": final.get("eval_count"),
    }


def score(case, res):
    text, wanted, check, cat = case
    calls = res["calls"] or res["written_calls"]
    names = [c["name"] for c in calls]
    want_tool = [w for w in wanted if w]
    r = {"tool": False, "args": False, "fake": False, "written": bool(res["written_calls"]), "rambling": False}
    if want_tool and names:
        hit = [c for c in calls if c["name"] in want_tool]
        r["tool"] = bool(hit)  # multi-action requests may be done one step at a time; the first step must be one of them
        r["args"] = r["tool"] and (check is None or any(_safe(check, c["args"]) for c in hit))
    elif not want_tool or None in wanted:
        r["tool"] = not names or (None in wanted and all(n in want_tool for n in names))
        r["args"] = r["tool"] and (check is None or not calls or any(_safe(check, c["args"]) for c in calls))
    if want_tool and not names and None not in wanted and ACTION_RX.search(text) and CLAIM_RX.search(res["text"] or ""):
        r["fake"] = True
    words = len((res["text"] or "").split())
    r["rambling"] = res["thinking_chars"] > 400 or words > (90 if cat == "chat" else 60)
    r["pass"] = r["tool"] and r["args"] and not r["fake"]
    return r


def _safe(fn, a):
    try:
        return bool(fn(a or {}))
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="*", default=CANDIDATES)
    ap.add_argument("--no-whisper", action="store_true")
    ap.add_argument("--ctx", type=int, default=8192)
    a = ap.parse_args()

    s = load_settings()
    root = _root(s.local_llm_url)
    if not server_up(s.local_llm_url):
        if not (find_ollama() and start_server(s.local_llm_url)):
            sys.exit("Ollama isn't running/installed. Install it (winget install Ollama.Ollama) and retry.")

    stt = None
    if not a.no_whisper:
        try:
            from zoha.stt import Transcriber

            print("Loading Whisper on the GPU (so the test matches real use)…")
            stt = Transcriber(s)
            print(f"  {stt.model_name} on {stt.device}")
        except Exception as e:
            print(f"  (couldn't load Whisper: {e}) – continuing without it")

    results = {}
    for model in a.models:
        print(f"\n=== {model} ===")
        if not ensure_model(root, model):
            continue
        try:
            caps = get_json(root + "/api/show", {"model": model}).get("capabilities") or []
        except Exception:
            caps = []
        think_flag = False if "thinking" in caps else None
        # warm-up (load into GPU) + VRAM share
        try:
            list(post_stream(root + "/api/chat", {"model": model, "messages": [{"role": "user", "content": "hi"}],
                                                   "stream": True, "keep_alive": "10m", "options": {"num_predict": 1, "num_ctx": a.ctx},
                                                   **({"think": False} if think_flag is False else {})}))
            ps = get_json(root + "/api/ps")
            want = model if ":" in model else model + ":latest"
            m = next((x for x in ps.get("models", []) if x.get("name") == want or x.get("model") == want), {})
            gpu = round((m.get("size_vram") or 0) / (m.get("size") or 1) * 100)
        except Exception as e:
            print(f"  ✗ couldn't load: {e}")
            continue
        print(f"  capabilities: {', '.join(caps) or '?'} | on GPU: {gpu}%")
        rows = []
        for i, case in enumerate(CASES, 1):
            try:
                res = run_case(root, model, s, case[0], think_flag, a.ctx)
                sc = score(case, res)
            except Exception as e:
                res, sc = {"error": str(e)[:200], "calls": [], "text": "", "first_s": 0, "total_s": 0, "thinking_chars": 0,
                           "written_calls": []}, {"pass": False, "tool": False, "args": False, "fake": False, "written": False, "rambling": False}
            mark = "✓" if sc["pass"] else ("✗ FAKE" if sc["fake"] else "✗")
            got = ", ".join(f"{c['name']}{json.dumps(c['args'])[:60]}" for c in (res["calls"] or res.get("written_calls") or [])) or \
                (res.get("error") or (res["text"] or "")[:60])
            print(f"  {i:2}. {mark:7} {res['total_s']:5.1f}s  {case[0][:52]:52} → {got}", flush=True)
            rows.append({"case": case[0], "category": case[3], **res, **{"score": sc}})
        n = len(rows)
        summ = {
            "model": model, "gpu_pct": gpu, "capabilities": caps,
            "pass": sum(r["score"]["pass"] for r in rows), "n": n,
            "fake": sum(r["score"]["fake"] for r in rows), "written": sum(r["score"]["written"] for r in rows),
            "rambling": sum(r["score"]["rambling"] for r in rows),
            "median_first_s": sorted(r["first_s"] for r in rows)[n // 2] if n else None,
            "median_total_s": sorted(r["total_s"] for r in rows)[n // 2] if n else None,
            "by_category": {},
        }
        for r in rows:
            c = summ["by_category"].setdefault(r["category"], [0, 0])
            c[0] += r["score"]["pass"]
            c[1] += 1
        results[model] = {"summary": summ, "rows": rows}
        print(f"  → {summ['pass']}/{n} correct, {summ['fake']} fake claims, median {summ['median_total_s']}s")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "bakeoff.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    cats = ["media", "apps", "browser", "pc", "info", "memory", "safety", "chat"]
    lines = ["# Zoha brain bake-off", "", f"{time.strftime('%Y-%m-%d %H:%M')} · {len(CASES)} commands · Whisper on GPU: {bool(stt)}", "",
             "| Model | Correct | Fake 'done' | Calls as text | Rambling | Median reply | On GPU | " + " | ".join(cats) + " |",
             "|---|---|---|---|---|---|---|" + "---|" * len(cats)]
    for m, r in sorted(results.items(), key=lambda kv: (-kv[1]["summary"]["pass"], kv[1]["summary"]["median_total_s"] or 99)):
        su = r["summary"]
        catv = " | ".join(f"{su['by_category'].get(c, [0, 0])[0]}/{su['by_category'].get(c, [0, 0])[1]}" for c in cats)
        lines.append(f"| {m} | **{su['pass']}/{su['n']}** | {su['fake']} | {su['written']} | {su['rambling']} | "
                     f"{su['median_total_s']}s | {su['gpu_pct']}% | {catv} |")
    (DATA_DIR / "bakeoff.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))
    print(f"\nSaved: {DATA_DIR / 'bakeoff.md'} and bakeoff.json")


if __name__ == "__main__":
    main()
