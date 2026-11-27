#!/usr/bin/env python3
"""
Zoha stress test: ~10,000 things you might say, run through Zoha's real brain, graded automatically.

    python stress_test.py                 # run everything (resumes where it stopped)
    python stress_test.py --limit 300     # quick sample
    python stress_test.py --fresh         # throw away old results and start over
    python stress_test.py --report        # just rebuild the report from saved results

Nothing happens on your PC: every tool is replaced by a fake that only records what Zoha
chose. No apps open, no volume changes, no shutdowns.

Close Zoha (tray → Quit) before running, so the GPU is free and she doesn't react to it.
Ctrl+C pauses safely. Run the same command again to continue.

Saves to data/stress/: results.jsonl (every case), report.md (summary), failures.jsonl.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _need(mod, pip_name=None):
    try:
        return __import__(mod)
    except ImportError:
        print(f"Installing {pip_name or mod} (one time)…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pip_name or mod])
        return __import__(mod)


_need("rich")
from rich.align import Align  # noqa: E402
from rich.console import Console, Group  # noqa: E402
from rich.live import Live  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402

from zoha import tools as T  # noqa: E402
from zoha.config import DATA_DIR, load_settings  # noqa: E402

OUT = DATA_DIR / "stress"
CASES = OUT / "cases.jsonl"
RESULTS = OUT / "results.jsonl"

TEAL, MINT, CORAL, AMBER, DIM, TEXT = "#5CD3C3", "#6EF5EE", "#E58B7B", "#E8C07D", "#6B7A77", "#ECEAE3"

# ── fake tools: realistic answers, zero side effects ─────────────────────────
CALLS: list = []
CURRENT = {"ctx": {}}


def _page_text():
    c = CURRENT["ctx"]
    url = c.get("browser_url", "")
    if "youtube.com" in url:
        ad = "an ad is playing – [3] button \"Skip ad\" (appears in 3s)\n" if "ad" in c.get("video", "") else ""
        return (f"Tab: {c.get('page', 'YouTube')}\nVideo: {c.get('video', 'playing')}\n{ad}[1] button \"Play/Pause\" [2] button \"Full screen\" "
                f"[4] button \"Subtitles/closed captions (c)\" pressed [5] link \"Next video\"")
    if "github.com" in url:
        return "Tab: AK-0017/dev-portfolio\n[1] link \"Code\" [2] link \"Issues\" [3] link \"README.md\""
    if url:
        return "Tab: Amazon.in : laptop stand\n[1] link \"Portronics laptop stand ₹999\"\n[2] link \"AmazonBasics stand ₹1,299\""
    return "Error: my browser isn't open."


def _stub(name):
    def f(**a):
        CALLS.append({"name": name, "args": a})
        g = lambda k, d="": a.get(k) or d  # noqa: E731
        R = {
            "open_app": lambda: f"Opened {g('name', 'it')}.",
            "close_app": lambda: f"Closed {g('name', 'it')}.",
            "open_website": lambda: f"Opened {g('site')} in your default browser.",
            "web_search": lambda: f"Searched Google for '{g('query')}'.",
            "web_lookup": lambda: f"Top result for '{g('query')}': (summary of the answer from the web).",
            "news_headlines": lambda: "1. Headline one. 2. Headline two. 3. Headline three.",
            "play_youtube": lambda: f"Playing '{g('query')}' on YouTube in my browser.",
            "play_spotify": lambda: f"Playing '{g('query')}' on Spotify.",
            "media_control": lambda: ("Spotify: Kesariya – Arijit Singh, playing." if g("action") == "status" else f"Done: {g('action')}."),
            "set_volume": lambda: (f"Volume set to {min(100, int(float(a['level'])))} percent." if a.get("level") is not None
                                   else f"Volume {g('change', 'changed')}."),
            "system_status": lambda: "CPU 18%, RAM 9.1 of 16 GB, GPU 42% at 58°C, battery not present.",
            "get_datetime": lambda: "Monday, 16 November 2026, 11:30 PM.",
            "get_weather": lambda: f"{g('city', 'Mumbai')}: 29°C, humid, light breeze. Tomorrow 30°C, clear.",
            "take_screenshot": lambda: "Screenshot saved to Pictures\\Screenshots\\shot.png.",
            "lock_pc": lambda: "Locked the PC.",
            "power": lambda: ("NOT DONE YET. Ask the user exactly: 'Should I "
                              + {"shutdown": "shut down", "restart": "restart", "sleep": "put to sleep"}.get(g("action"), g("action"))
                              + " the PC? Say yes to confirm.' Do nothing else.") if g("action") != "cancel" else "Cancelled.",
            "open_folder": lambda: f"Opened {g('folder')}.",
            "find_files": lambda: f"Found 2 files for '{g('query')}': C:\\docs\\{g('query')}.pdf, C:\\old\\{g('query')}.docx"
                                  + (" – opened the first." if a.get("open_first") else "."),
            "open_path": lambda: f"Opened {g('path')}.",
            "create_note": lambda: "Saved the note.",
            "read_notes": lambda: "1. buy milk 2. call the client 3. revise OS.",
            "type_text": lambda: f"Typed {len(str(g('text')))} characters into the active window.",
            "clipboard": lambda: ("Clipboard: 'hello world'" if g("action") == "read" else "Copied to the clipboard."),
            "set_timer": lambda: "Timer set — goes off soon.",
            "set_reminder": lambda: "Reminder set.",
            "list_timers": lambda: "It's still set: your tea timer goes off in 4 minutes.",
            "cancel_timer": lambda: "Cancelled 1.",
            "remember": lambda: "Got it, I'll remember that.",
            "forget": lambda: "Forgot 1 thing.",
            "browser_open": lambda: f"Opened {g('target')} in my browser.",
            "browser_read": _page_text,
            "browser_click": lambda: "Clicked.",
            "browser_type": lambda: "Typed it.",
            "browser_select": lambda: "Selected.",
            "browser_press": lambda: f"Pressed {g('key')}.",
            "browser_scroll": lambda: f"Scrolled {g('direction')}.",
            "browser_nav": lambda: f"Went {g('action')}.",
            "browser_tabs": lambda: "Tabs: [0] YouTube, [1] Amazon." if g("action") == "list" else f"Tab {g('action')} done.",
            "browser_video": lambda: f"Video: {g('action')} done.",
            "browser_window": lambda: f"Window {g('state')}.",
            "browser_look": lambda: "I can see a YouTube video page with a video playing.",
            "browser_close": lambda: "Closed my browser.",
        }
        return R.get(name, lambda: "Done.")()
    return f


def install_stubs():
    for n, t in T.REGISTRY.items():
        t.fn = _stub(n)
    assert all(getattr(t.fn, "__qualname__", "").startswith("_stub") for t in T.REGISTRY.values()), "a real tool slipped through"
    T.CTX.vision = None


# ── grading ──────────────────────────────────────────────────────────────────
from stress.grading import DESTRUCTIVE, _check, _minutes, grade, match, parser_route  # noqa: E402,F401


def awareness(ctx) -> str:
    lines = []
    if ctx.get("media"):
        lines.append("Media: " + ctx["media"].replace("Spotify: ", "") + (" in Spotify." if "Spotify" in ctx["media"] else ""))
    if ctx.get("browser_open"):
        v = f" (video {ctx['video']})" if ctx.get("video") else ""
        lines.append(f"Your browser (browser_* tools) is open on: {ctx.get('page', '')} – {ctx.get('browser_url', '')}{v}")
    wins = (["Zoha's browser – " + ctx.get("page", "")] if ctx.get("browser_open") else []) + ["Visual Studio Code", "File Explorer"]
    lines.append("Open windows (front first): " + "; ".join(wins))
    return "\n".join(lines)


# ── flags from the brain's own log (lie caught, forced pick, …) ──────────────
class FlagLog(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.flags = set()

    def emit(self, rec):
        m = rec.getMessage()
        if m.startswith("Unbacked reply"):
            self.flags.add("model_claimed")
        elif m.startswith("Forced choice"):
            self.flags.add("forced")
        elif m.startswith("Model wrote"):
            self.flags.add("written_call")
        elif m.startswith("No action chosen"):
            self.flags.add("honest_replacement")


# ── dashboard ────────────────────────────────────────────────────────────────
def fmt_dur(s):
    s = int(max(0, s))
    h, m = divmod(s // 60, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s % 60:02d}s"


def bar(frac, width, color):
    full = int(frac * width)
    part = " ▏▎▍▌▋▊▉"[int((frac * width - full) * 8)] if full < width else ""
    return Text("█" * full + part, style=color) + Text("·" * (width - full - len(part)), style=DIM)


class Dash:
    def __init__(self, total, model, done_rows):
        self.total, self.model = total, model
        self.t0 = time.time()
        self.durs = deque(maxlen=80)
        self.recent = deque(maxlen=9)
        self.n = self.ok = self.sys_ok = self.lies = self.parser = self.err = 0
        self.cats = defaultdict(lambda: [0, 0])
        self.reasons = Counter()
        self.gpu = ""
        self.gpu_at = 0
        self.session_n = 0
        for r in done_rows:
            self._count(r)

    def _count(self, r):
        self.n += 1
        self.ok += r["ok"]
        self.sys_ok += r["system_ok"]
        self.lies += "model_claimed" in r["flags"]
        self.parser += r["route"] == "parser"
        self.err += bool(r.get("error"))
        c = self.cats[r["cat"]]
        c[0] += r["ok"]
        c[1] += 1
        if r["reason"]:
            self.reasons[r["reason"]] += 1

    def add(self, r, dur):
        self._count(r)
        self.session_n += 1
        self.durs.append(dur)
        self.recent.appendleft(r)

    def eta(self):
        left = self.total - self.n
        avg = (sum(self.durs) / len(self.durs)) if self.durs else 3.2
        return left * avg, avg

    def _gpu(self):
        if time.time() - self.gpu_at > 15:
            self.gpu_at = time.time()
            try:
                o = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total",
                                    "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                                   creationflags=0x08000000 if os.name == "nt" else 0).stdout.strip().split(",")
                self.gpu = f"GPU {o[0].strip()}%  ·  {o[1].strip()}°C  ·  VRAM {int(o[2]) / 1024:.1f}/{int(o[3]) / 1024:.1f} GB"
            except Exception:
                self.gpu = ""
        return self.gpu

    def render(self):
        frac = self.n / self.total if self.total else 1
        left, avg = self.eta()
        finish = time.strftime("%I:%M %p", time.localtime(time.time() + left)).lstrip("0")
        pct = lambda a, b: f"{a / b * 100:.1f}%" if b else "–"  # noqa: E731

        head = Text.assemble(("ZOHA ", f"bold {MINT}"), ("stress test", f"bold {TEXT}"), ("   ·   ", DIM), (self.model, TEAL),
                             ("   ·   ", DIM), (f"{self.total:,} conversations", DIM))
        big = Text.assemble((f"{frac * 100:5.1f}%", f"bold {MINT}"), ("  ", ""), (f"{self.n:,} / {self.total:,}", TEXT))
        times = Text.assemble(("elapsed ", DIM), (fmt_dur(time.time() - self.t0), TEXT), ("    left ", DIM),
                              (fmt_dur(left) if self.session_n >= 3 else "measuring…", f"bold {AMBER}"),
                              ("    done around ", DIM), (finish if self.session_n >= 3 else "…", f"bold {TEXT}"),
                              ("    ", ""), (f"{avg:.1f}s each", DIM))
        prog = Group(Align.center(big), Align.center(bar(frac, max(20, min(90, Console().width - 16)), TEAL)), Align.center(times))

        st = Table.grid(expand=True, padding=(0, 2))
        for _ in range(4):
            st.add_column(justify="center")
        cell = lambda v, lab, col: Text.assemble((v, f"bold {col}"), ("\n" + lab, DIM))  # noqa: E731
        st.add_row(cell(pct(self.ok, self.n), "AI alone correct", MINT),
                   cell(pct(self.sys_ok, self.n), "Zoha overall (parser + AI)", TEAL),
                   cell(f"{self.lies:,}", "lies caught by the guard", CORAL if self.lies else MINT),
                   cell(pct(self.parser, self.n), "handled instantly (no AI)", TEXT))

        w = Console().width
        bw = max(6, min(22, w // 2 - 34))
        ct = Table(box=None, expand=True, show_header=False, padding=(0, 1))
        ct.add_column(style=TEXT, width=9, no_wrap=True, overflow="ellipsis")
        ct.add_column(width=bw + 1, no_wrap=True)
        ct.add_column(justify="right", width=4, no_wrap=True)
        ct.add_column(justify="right", style=DIM, width=5, no_wrap=True)
        for cat, (ok, n) in sorted(self.cats.items(), key=lambda kv: kv[1][0] / max(1, kv[1][1])):
            f = ok / n if n else 0
            col = MINT if f >= 0.9 else AMBER if f >= 0.7 else CORAL
            ct.add_row(cat, bar(f, bw, col), Text(f"{f * 100:.0f}%", style=col), f"{n}")

        feed = Table(box=None, expand=True, show_header=False, padding=(0, 1))
        feed.add_column(width=2)
        feed.add_column(ratio=3, no_wrap=True, overflow="ellipsis")
        feed.add_column(ratio=2, no_wrap=True, overflow="ellipsis", style=DIM)
        for r in self.recent:
            got = ", ".join(f"{c['name']}" for c in r["calls"]) or (r["reply"][:50] if r["reply"] else "–")
            feed.add_row(Text("✓", style=MINT) if r["ok"] else Text("✗", style=CORAL),
                         Text(r["text"], style=TEXT if r["ok"] else CORAL), got)

        why = Text.assemble(*[x for k, v in self.reasons.most_common(5) for x in ((f"{k.replace('_', ' ')} ", DIM), (f"{v}   ", AMBER))]) \
            if self.reasons else Text("no failures yet", style=DIM)

        cols = Table.grid(expand=True, padding=(0, 2))
        cols.add_column(ratio=1)
        cols.add_column(ratio=1)
        cols.add_row(Panel(ct, title="by category", title_align="left", border_style=DIM),
                     Panel(feed, title="live", title_align="left", border_style=DIM))
        foot = Text.assemble((self._gpu() + "    " if self._gpu() else "", DIM), ("Ctrl+C pauses safely · run again to continue", DIM))
        return Panel(Group(Align.center(head), Text(""), prog, Text(""), st, Text(""), cols,
                           Panel(why, title="why cases fail", title_align="left", border_style=DIM), Align.center(foot)),
                     border_style=TEAL, padding=(1, 2))


def set_title(s):
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(s)
        except Exception:
            pass


def keep_awake(on=True):
    """Stop Windows from sleeping during a 9-hour run (the screen may still turn off)."""
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))
            if on:
                ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)  # below normal
        except Exception:
            pass


# ── report ───────────────────────────────────────────────────────────────────
def load_rows():
    rows = {}
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                rows[r["id"]] = r
            except Exception:
                pass
    return list(rows.values())


def write_report(rows, model):
    if not rows:
        return
    n = len(rows)
    ok = sum(r["ok"] for r in rows)
    sys_ok = sum(r["system_ok"] for r in rows)
    lies = sum("model_claimed" in r["flags"] for r in rows)
    sys_lies = sum(r["reason"] == "fake_done" for r in rows)
    parser = sum(r["route"] == "parser" for r in rows)
    durs = sorted(r["secs"] for r in rows if r.get("secs"))
    cats = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        c = cats[r["cat"]]
        c[0] += r["ok"]
        c[1] += r["system_ok"]
        c[2] += 1
    L = [f"# Zoha stress test — {model}", "", f"{time.strftime('%d %b %Y %H:%M')} · {n:,} conversations", "",
         f"- **AI alone correct:** {ok:,}/{n:,} ({ok / n * 100:.1f}%)",
         f"- **Zoha overall (instant parser first, then AI):** {sys_ok:,}/{n:,} ({sys_ok / n * 100:.1f}%)",
         f"- **Handled instantly without the AI:** {parser / n * 100:.1f}%",
         f"- **AI tried to fake a 'done' (caught by the guard):** {lies:,}",
         f"- **Fake 'done' that got through:** {sys_lies:,}",
         f"- **Median time per conversation:** {durs[len(durs) // 2] if durs else 0:.1f}s", "",
         "| Category | AI alone | Zoha overall | Cases |", "|---|---|---|---|"]
    for cat, (a, s, m) in sorted(cats.items(), key=lambda kv: kv[1][0] / kv[1][2]):
        L.append(f"| {cat} | {a / m * 100:.0f}% | {s / m * 100:.0f}% | {m} |")
    L += ["", "## Why the AI failed", "", "| Reason | Count |", "|---|---|"]
    for k, v in Counter(r["reason"] for r in rows if r["reason"]).most_common():
        L.append(f"| {k.replace('_', ' ')} | {v} |")
    L += ["", "## Most common mix-ups (expected → got)", ""]
    mix = Counter()
    for r in rows:
        if not r["ok"]:
            want = "/".join(r["want"]) or "(no action)"
            got = ", ".join(c["name"] for c in r["calls"]) or "(no action)"
            mix[(r["cat"], want, got)] += 1
    for (cat, want, got), v in mix.most_common(25):
        L.append(f"- **{cat}**: {want} → {got} ×{v}")
    L += ["", "## Examples of failures", ""]
    seen = Counter()
    for r in rows:
        if not r["ok"] and seen[r["cat"]] < 4:
            seen[r["cat"]] += 1
            got = "; ".join(f"{c['name']} {json.dumps(c['args'], ensure_ascii=False)}" for c in r["calls"]) or "(no action)"
            L.append(f"- [{r['cat']}] “{r['text']}” → {got} — said: “{(r['reply'] or '')[:120]}” ({r['reason']})")
    suffix = "_round2" if RESULTS.name.endswith("round2.jsonl") else ""
    (OUT / f"report{suffix}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    with (OUT / f"failures{suffix}.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            if not r["ok"]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_comparison(model):
    """Round 1 vs round 2 on exactly the same cases. Round 1 is re-graded with the corrected answers, so it's fair."""
    cases = {}
    for line in CASES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            cases[c["id"]] = c
    r1 = {}
    for line in (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            r1[r["id"]] = r
        except Exception:
            pass
    r2 = {r["id"]: r for r in load_rows() if r.get("model") == model}
    ids = [i for i in r2 if i in r1 and i in cases]
    if not ids:
        return
    stats = {"ai1": 0, "ai2": 0, "sys1": 0, "sys2": 0, "fixed": 0, "broke": 0}
    cats = defaultdict(lambda: [0, 0, 0, 0, 0])
    broke_examples = []
    for i in ids:
        c, a, b = cases[i], r1[i], r2[i]
        ok1 = bool(grade(c, a["calls"], a["reply"])[0])
        if a.get("error"):
            ok1 = False
        p1 = a.get("parser_calls") or []
        if a["route"] == "parser":
            s1 = bool(grade(c, p1, "Done.")[0])
        elif (a["route"] or "").startswith("control:"):
            s1 = bool(c["expect"].get("nopower") or c["expect"].get("none"))
        else:
            s1 = ok1
        ok2, s2 = bool(b["ok"]), bool(b["system_ok"])
        stats["ai1"] += ok1
        stats["ai2"] += ok2
        stats["sys1"] += s1
        stats["sys2"] += s2
        stats["fixed"] += (not s1) and s2
        stats["broke"] += s1 and not s2
        k = cats[c["cat"]]
        k[0] += ok1
        k[1] += ok2
        k[2] += s1
        k[3] += s2
        k[4] += 1
        if s1 and not s2 and len(broke_examples) < 25:
            broke_examples.append(b)
    n = len(ids)
    pct = lambda x: f"{x / n * 100:.1f}%"  # noqa: E731
    L = [f"# Zoha stress test — round 2 vs round 1 ({model})", "", f"{time.strftime('%d %b %Y %H:%M')} · same {n:,} cases in both rounds "
         "(every round-1 failure + a random sample of the rest; round 1 re-graded with the corrected answers)", "",
         "| | Round 1 | Round 2 |", "|---|---|---|",
         f"| AI alone correct | {pct(stats['ai1'])} | {pct(stats['ai2'])} |",
         f"| **Zoha overall (parser + AI)** | {pct(stats['sys1'])} | **{pct(stats['sys2'])}** |", "",
         f"- Fixed: **{stats['fixed']:,}** cases that failed before now pass",
         f"- Broken: **{stats['broke']:,}** cases that passed before now fail", "",
         "| Category | AI r1 | AI r2 | Zoha r1 | Zoha r2 | Cases |", "|---|---|---|---|---|---|"]
    for cat, (a1, a2, s1, s2, m) in sorted(cats.items(), key=lambda kv: kv[1][3] / kv[1][4]):
        L.append(f"| {cat} | {a1 / m * 100:.0f}% | {a2 / m * 100:.0f}% | {s1 / m * 100:.0f}% | {s2 / m * 100:.0f}% | {m} |")
    if broke_examples:
        L += ["", "## Newly broken (examples)", ""]
        for b in broke_examples:
            got = "; ".join(f"{c['name']} {json.dumps(c['args'], ensure_ascii=False)}" for c in (b["parser_calls"] if b["route"] == "parser" else b["calls"])) or "(no action)"
            L.append(f"- [{b['cat']}] “{b['text']}” → {got} ({b['route'] or 'AI'})")
    (OUT / "comparison_round2.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ── main loop ────────────────────────────────────────────────────────────────
async def run_case(brain, case, flaglog):
    CALLS.clear()
    flaglog.flags = set()
    now = time.time()
    brain.memory.history = [x for u, a in case["hist"] for x in ({"role": "user", "text": u, "t": now - 30},
                                                                   {"role": "assistant", "text": a, "t": now - 29})]
    brain._recent_tools = {"play_youtube", "browser_video"} if any("YouTube" in a for _, a in case["hist"]) else set()
    brain.awareness = awareness(case["ctx"])
    T.CTX.browser_open_hint = bool(case["ctx"].get("browser_open"))
    CURRENT["ctx"] = case["ctx"]
    T.CTX.last_user_text = case["text"]
    T.CTX.turn_started = now
    text, err = [], None

    async def go():
        async for ev in brain.run(case["text"], "voice"):
            if ev[0] == "text":
                text.append(ev[1])

    try:
        await asyncio.wait_for(go(), timeout=120)
    except asyncio.TimeoutError:
        err = "timeout"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:300]
    return list(CALLS), "".join(text).strip(), err


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="only run this many cases")
    ap.add_argument("--fresh", action="store_true", help="delete old results and start over")
    ap.add_argument("--model", default="", help="Ollama model (default: the one in Zoha's settings)")
    ap.add_argument("--report", action="store_true", help="only rebuild the report")
    ap.add_argument("--rerun", action="store_true",
                    help="round 2: re-test every case that failed in round 1 plus a random 1,500 others, and compare")
    ap.add_argument("--sample", type=int, default=1500, help="random extra cases for --rerun")
    ap.add_argument("--cases-file", default="", help="run these cases instead (used by train/compare.py)")
    ap.add_argument("--results-name", default="", help="results file name inside data/stress (used by train/compare.py)")
    a = ap.parse_args()
    global RESULTS
    if a.rerun:
        RESULTS = OUT / "results_round2.jsonl"
    if a.results_name:
        RESULTS = OUT / a.results_name

    con = Console()
    OUT.mkdir(parents=True, exist_ok=True)
    s = load_settings()
    model = a.model or s.local_llm_model
    if a.report:
        write_report(load_rows(), model)
        if a.rerun:
            write_comparison(model)
        con.print(f"[{TEAL}]Report:[/] {OUT / ('report_round2.md' if a.rerun else 'report.md')}")
        return
    if not CASES.exists() or a.rerun:
        from stress.cases import write

        write(CASES)  # same sentences as round 1, with the corrected answers
    src = Path(a.cases_file) if a.cases_file else CASES
    cases = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
    if a.rerun:
        r1 = {}
        for line in (OUT / "results.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                r1[r["id"]] = r
            except Exception:
                pass
        if not r1:
            con.print(f"[{CORAL}]No round-1 results found (data/stress/results.jsonl).[/]")
            sys.exit(1)
        failed = {i for i, r in r1.items() if not r["ok"] or not r["system_ok"]}
        import random as _r

        others = sorted(set(r1) - failed)
        extra = set(_r.Random(7).sample(others, min(a.sample, len(others))))
        cases = [c for c in cases if c["id"] in failed | extra]
        con.print(f"[{TEAL}]Round 2:[/] {len(failed):,} round-1 failures + {len(extra):,} random others = {len(cases):,} cases")
    if a.limit:
        cases = cases[: a.limit]
    if a.fresh and RESULTS.exists():
        RESULTS.unlink()
    done_rows = [r for r in load_rows() if r.get("model") == model]
    done = {r["id"] for r in done_rows}
    todo = [c for c in cases if c["id"] not in done]
    ids = {c["id"] for c in cases}
    done_rows = [r for r in done_rows if r["id"] in ids]

    from zoha.brain import Brain
    from zoha.local_llm import ensure_ready, model_caps, warm_up
    from zoha.memory import Memory

    con.print(f"[{TEAL}]Getting {model} ready on the GPU…[/]")
    ok, runtime = ensure_ready(s.local_llm_url, model, int(s.local_llm_ctx), progress=lambda m: con.print(f"  [{DIM}]{m}[/]"))
    if not ok:
        con.print(f"[{CORAL}]{runtime}[/]")
        sys.exit(1)
    caps = model_caps(s.local_llm_url, model)
    try:
        warm_up(s.local_llm_url, runtime)
    except Exception:
        pass

    install_stubs()
    logging.basicConfig(level=logging.WARNING)
    blog = logging.getLogger("zoha.brain")
    blog.setLevel(logging.INFO)
    blog.propagate = False
    flaglog = FlagLog()
    blog.addHandler(flaglog)

    s.llm_provider, s.llm_fallback = "local", "none"
    brain = Brain(s, Memory(OUT / "scratch_memory.json"))
    brain.memory.facts = []
    brain.local_runtime_model = runtime
    brain.local_thinks = "thinking" in (caps or [])

    dash = Dash(len(cases), model, done_rows)
    if not todo:
        if not a.results_name:
            write_report(load_rows(), model)
        con.print(f"[{MINT}]All {len(cases):,} cases are already done.[/] Report: {OUT / 'report.md'}  (use --fresh to redo)")
        return
    keep_awake(True)
    loop = asyncio.new_event_loop()
    stopped = False
    try:
        with Live(dash.render(), console=con, refresh_per_second=2, screen=True) as live, RESULTS.open("a", encoding="utf-8") as out:
            for case in todo:
                t0 = time.time()
                route, pcalls = parser_route(case)
                calls, reply, err = loop.run_until_complete(run_case(brain, case, flaglog))
                ok_, reason = grade(case, calls, reply)
                if err:
                    ok_, reason = False, "error"
                if route == "parser":
                    sys_ok, _ = grade(case, pcalls, "Done.")
                elif route and route.startswith("control:"):
                    sys_ok = case["expect"].get("nopower") or case["expect"].get("none") or False
                else:
                    sys_ok = ok_
                e = case["expect"]
                want = sorted({t for sp in e.get("any", []) + e.get("all", []) for t in sp["tools"]}) if ("any" in e or "all" in e) else []
                row = {"id": case["id"], "cat": case["cat"], "split": case["split"], "text": case["text"], "ctx": case["ctx"],
                       "hist": case["hist"], "expect": e, "want": want, "calls": calls, "reply": reply, "ok": bool(ok_),
                       "reason": reason, "route": route, "parser_calls": pcalls, "system_ok": bool(sys_ok),
                       "flags": sorted(flaglog.flags), "error": err, "secs": round(time.time() - t0, 2), "model": model}
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                dash.add(row, time.time() - t0)
                left, _ = dash.eta()
                set_title(f"Zoha test {dash.n / dash.total * 100:.0f}% · {fmt_dur(left)} left")
                live.update(dash.render())
                if dash.session_n % 250 == 0:
                    write_report(load_rows(), model)
    except KeyboardInterrupt:
        stopped = True
    finally:
        keep_awake(False)
        loop.close()
    rows = [r for r in load_rows() if r.get("model") == model]
    if a.results_name:  # train/compare.py writes its own report
        return
    write_report(rows, model)
    if a.rerun:
        write_comparison(model)
    set_title("Zoha test – paused" if stopped else "Zoha test – done")
    con.print(dash.render())
    if stopped:
        con.print(f"\n[{AMBER}]Paused at {dash.n:,}/{dash.total:,}.[/] Run [bold]python stress_test.py[/] again to continue.")
    else:
        con.print(f"\n[{MINT}]Finished![/] Report: {OUT / ('comparison_round2.md' if a.rerun else 'report.md')}")
        if os.name == "nt":
            try:
                import winsound

                winsound.MessageBeep()
            except Exception:
                pass
    con.print(f"[{DIM}]Send me data/stress/" + ("comparison_round2.md and data/stress/results_round2.jsonl[/]" if a.rerun
                                                   else "report.md and data/stress/results.jsonl[/]"))


if __name__ == "__main__":
    main()
