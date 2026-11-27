"""
One shared "ask first" gate for actions that leave the computer (publishing a site, and so on).

The AI can only REQUEST an action. It gets back a sentence to read out and the action is held for
5 minutes. The engine runs it only when the user's very next message is a clear yes; any other
message cancels it, so a later "yes" can never trigger something old.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, Optional

WINDOW = 5 * 60
YES_RX = re.compile(r"^\W*(?:yes|yeah|yep|yup|sure|ok(?:ay)?|go ahead|do it|haan|ha|kar do|confirm(?:ed)?|please do|proceed)\W*(?:please|now|zoha)?\W*$", re.I)
NO_RX = re.compile(r"^\W*(?:no|nope|nah|nahi|cancel|don'?t|stop|wait|never ?mind|not now|rehne do)\b", re.I)

_lock = threading.Lock()
_pending: Optional[dict] = None


def request(kind: str, summary: str, action: Callable[[], str]) -> str:
    """Hold `action` until the user says yes. Returns what the AI must ask, word for word."""
    global _pending
    with _lock:
        _pending = {"kind": kind, "summary": summary, "action": action, "t": time.time()}
    return f"NOT DONE YET. Ask the user exactly: '{summary} Should I go ahead?' and then wait for their answer. Do nothing else."


def pending() -> Optional[dict]:
    with _lock:
        if _pending and time.time() - _pending["t"] < WINDOW:
            return dict(_pending)
    return None


def is_yes(text: str) -> bool:
    return bool(YES_RX.match(text or ""))


def is_no(text: str) -> bool:
    return bool(NO_RX.match(text or "")) and len((text or "").split()) <= 3


def cancel() -> None:
    global _pending
    with _lock:
        _pending = None


def apply() -> str:
    """Run the held action once (only the engine calls this, after a yes)."""
    global _pending
    with _lock:
        p, _pending = _pending, None
    if not p or time.time() - p["t"] >= WINDOW:
        return "Error: that request ran out of time, so nothing was done. Ask me again."
    try:
        return p["action"]()
    except Exception as e:  # noqa: BLE001
        return f"Error: it didn't work ({type(e).__name__}). Nothing else was changed."
