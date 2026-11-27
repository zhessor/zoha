"""
Teach Zoha a routine by doing it once with her, then run it with one phrase ("start work mode").

She records the SAFE tool actions you ask for (open an app, set the volume, open a site, play music ...)
and replays that same list. It does not record the mouse or keyboard. Anything risky is never recorded:
shutdown/restart/sleep, website changes, publishing, writing files, and other routines.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Dict, List, Optional

from . import tools as T
from .config import DATA_DIR
from .tools import tool

NEVER_RECORD_PREFIX = ("site_", "routine_", "browser_")
NEVER_RECORD = {"power", "write_file", "improve_file", "forget", "type_text", "clipboard", "make_quotation", "add_invoice",
                "mark_paid", "draft_followup", "list_unpaid"}
MAX_STEPS = 12
_lock = threading.Lock()
_rec: Optional[dict] = None   # {"name": str, "steps": [ {tool, args} ], "skipped": [names]}


def allowed(name: str) -> bool:
    return name in T.REGISTRY and name not in NEVER_RECORD and not name.startswith(NEVER_RECORD_PREFIX)


def _file():
    return DATA_DIR / "routines.json"


def load() -> Dict[str, List[dict]]:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _store(d: Dict[str, List[dict]]) -> None:
    _file().parent.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


def norm(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())).strip()[:40]


def observe(name: str, args: dict, result: str) -> None:
    """Called by tools.call_tool after every tool run; keeps successful, safe steps while recording."""
    with _lock:
        if not _rec:
            return
        if str(result).startswith("Error") or name.startswith("routine_"):
            return
        if not allowed(name):
            _rec["skipped"].append(name)
            return
        if len(_rec["steps"]) < MAX_STEPS:
            _rec["steps"].append({"tool": name, "args": dict(args or {})})


T.RECORDER = observe


@tool("routine_record", "Start learning a routine. Use for 'learn this as work mode', 'record a routine called morning', "
      "'watch what I ask and remember it'. After this, the user asks for the steps normally; when they say 'that's it' call routine_save.",
      "Learning a routine", "🎓", name=("string", "The phrase that will run it later, e.g. 'work mode'", True))
def routine_record(name: str) -> str:
    global _rec
    n = norm(name)
    if not n:
        return "Error: what should I call this routine?"
    with _lock:
        _rec = {"name": n, "steps": [], "skipped": []}
    return (f"Recording '{n}'. Tell me each step as you normally would, and say 'that's it' when done. "
            "I only record safe actions like opening apps, volume and music, never shutdown or sending things.")


@tool("routine_save", "Finish and save the routine being recorded (the user says 'that's it', 'save it', 'done').", "Saving routine", "💾")
def routine_save() -> str:
    global _rec
    with _lock:
        rec, _rec = _rec, None
    if not rec:
        return "Error: I'm not recording a routine right now."
    if not rec["steps"]:
        return "Nothing to save: I didn't see any steps I'm allowed to record."
    d = load()
    d[rec["name"]] = rec["steps"]
    _store(d)
    skipped = sorted(set(rec["skipped"]))
    note = f" I left out {', '.join(skipped)} because it's not safe to repeat automatically." if skipped else ""
    return f"Saved '{rec['name']}' with {len(rec['steps'])} steps. Say 'run {rec['name']}' any time.{note}"


@tool("routine_run", "Run a saved routine by name: 'start work mode', 'run my morning routine'.", "Running routine", "▶️",
      name=("string", "Routine name", True))
def routine_run(name: str) -> str:
    d = load()
    n = norm(name)
    hit = n if n in d else next((k for k in d if n and (n in k or k in n)), None)
    if not hit:
        return f"Error: I don't have a routine called '{name}'. Saved: {', '.join(d) or 'none yet'}."
    done, failed = [], []
    for step in d[hit]:
        if not allowed(step["tool"]):
            failed.append(step["tool"])
            continue
        res = T.call_tool(step["tool"], step["args"])
        (failed if res.startswith("Error") else done).append(step["tool"])
    msg = f"Ran '{hit}': {len(done)} of {len(d[hit])} steps done."
    return msg + (f" Couldn't do: {', '.join(failed)}." if failed else "")


@tool("routine_list", "List the routines Zoha has learned.", "My routines", "📋")
def routine_list() -> str:
    d = load()
    return "; ".join(f"{k} ({len(v)} steps)" for k, v in d.items()) or "No routines yet."


@tool("routine_forget", "Delete one saved routine by name.", "Forgetting routine", "🗑️", name=("string", "Routine name", True))
def routine_forget(name: str) -> str:
    d = load()
    n = norm(name)
    if n not in d:
        return f"Error: no routine called '{name}'."
    del d[n]
    _store(d)
    return f"Forgot '{n}'."
