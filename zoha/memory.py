"""Persistent memory: long-term facts + recent conversation, stored in data/memory.json."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, List

from .config import DATA_DIR


class Memory:
    def __init__(self, path: Path = DATA_DIR / "memory.json", max_turns: int = 12):
        self.path = path
        self.max_turns = max_turns
        self._lock = threading.Lock()
        self.facts: List[Dict] = []
        self.history: List[Dict] = []  # [{"role": "user"|"assistant", "text": str, "t": float}]
        self.summary: Dict = {}         # {"text": str, "t": float} – older turns of this conversation, condensed
        self.on_dropped = None          # callback(turns) when old turns fall out of the window (engine summarises them)
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.facts = data.get("facts", [])
            self.history = data.get("history", [])[-self.max_turns * 2 :]
            self.summary = data.get("summary", {}) or {}
        except Exception:
            pass

    def save(self):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"facts": self.facts, "history": self.history[-200:], "summary": self.summary}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self.path)

    # conversation ----------------------------------------------------------
    def add_turn(self, user: str, assistant: str):
        now = time.time()
        self.history.append({"role": "user", "text": user, "t": now})
        self.history.append({"role": "assistant", "text": assistant, "t": now})
        keep = max(2, self.max_turns * 2)
        dropped = self.history[:-keep] if len(self.history) > keep else []
        self.history = self.history[-keep:]
        self.save()
        cutoff = now - 6 * 3600
        dropped = [d for d in dropped if d.get("t", 0) >= cutoff]
        if dropped and self.on_dropped:
            try:
                self.on_dropped(dropped)
            except Exception:
                pass

    def summary_text(self) -> str:
        """Running summary of the current conversation (forgotten after 6 idle hours, like the history)."""
        if self.summary.get("text") and time.time() - self.summary.get("t", 0) < 6 * 3600:
            return self.summary["text"]
        return ""

    def set_summary(self, text: str):
        self.summary = {"text": text, "t": time.time()}
        self.save()

    def recent(self) -> List[Dict]:
        # drop context older than 6 hours so a new session starts fresh-ish
        cutoff = time.time() - 6 * 3600
        return [h for h in self.history if h.get("t", 0) >= cutoff][-self.max_turns * 2 :]

    def clear_conversation(self):
        self.history = []
        self.summary = {}
        self.save()

    # facts -----------------------------------------------------------------
    def remember(self, fact: str) -> str:
        fact = fact.strip().rstrip(".")
        if not fact:
            return "Nothing to remember."
        for f in self.facts:
            if f["text"].lower() == fact.lower():
                return "I already know that."
        self.facts.append({"text": fact, "t": time.time()})
        self.save()
        return f"Got it. I'll remember that {fact}."

    def forget(self, query: str) -> str:
        q = query.lower().strip()
        before = len(self.facts)
        self.facts = [f for f in self.facts if q not in f["text"].lower()]
        removed = before - len(self.facts)
        self.save()
        return f"Forgot {removed} item{'s' if removed != 1 else ''}." if removed else "I had nothing matching that."

    def facts_text(self) -> str:
        return "\n".join(f"- {f['text']}" for f in self.facts[-60:])
