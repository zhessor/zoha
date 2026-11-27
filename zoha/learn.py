"""How Zoha learns between conversations — without retraining the model.

  * Journal      data/turns.jsonl – every turn: what was heard, which tools ran with which arguments,
                 their results, the reply, timings, lie-guard flags. Corrections are added later as
                 feedback lines. This is also the raw material for future training.
  * Corrections  "no, I meant Air LLM" / "I'm talking about GitHub.com" → the misheard words are
                 replaced from now on, the right word is added to Whisper's vocabulary, and the
                 previous request is redone with the fix.  Stored in data/learned.json.
  * Recall       past conversations are searched (keyword ranking, no extra model) and the best
                 matches are handed to the brain when they look relevant.
  * Recipes      multi-step tasks that worked (and weren't corrected) are saved; when a similar
                 request comes in, the brain gets the steps as a hint.
  * Summary      older turns of the current conversation are folded into a short running summary
                 (see Memory.summary), so long sessions keep their thread without a huge prompt.
"""

from __future__ import annotations

import difflib
import json
import logging
import math
import re
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import DATA_DIR

log = logging.getLogger("zoha.learn")
I = re.I

SEED_VOCAB = ["Zoha", "AirLLM", "Playwright", "GitHub", "Kaggle", "Ollama", "Qwen"]
STOP = set("""a an the and or but if then so to of in on at for from by with about into over under this that these those it its
is are was were be been am do does did have has had i you he she we they me my your our his her them us please pls can could would
will shall should just now ok okay hey hi zoha bro yaar na also there here what which who how when where why want like get go
open close start play search show tell give make set some any one more all not no yes really actually thanks thank""".split())
COMPLAINT_RX = re.compile(r"^(?:no+|nope|wrong|galat|nahi|not that|that'?s (?:not|wrong)|you didn'?t|it didn'?t|i said|i asked|i told)\b"
                          r"|\b(?:didn'?t (?:work|open|happen)|not what i (?:said|asked|meant)|that'?s wrong)\b", I)
_CORR = [  # (pattern, has_y)
    (re.compile(r"^(?:no+|nope|nahi|not that|wrong)[\s,.!]+i\s+(?:meant|mean|said)\s+(?P<x>.+)$", I), False),
    (re.compile(r"^(?:no+[\s,.!]+)?i(?:'m| am| was)\s+(?:talking|referring|asking)\s+about\s+(?P<x>.+)$", I), False),
    (re.compile(r"^(?:no+[\s,.!]+)?(?:it'?s|its|it is|i said|i meant)\s+(?P<x>.+?)[\s,]+not\s+(?P<y>.+)$", I), True),
    (re.compile(r"^(?:no+[\s,.!]+)?not\s+(?P<y>.+?)[\s,]+(?:but\s+|it'?s\s+)?(?P<x>.+)$", I), True),
    (re.compile(r"^(?:when|if)\s+i\s+say\s+(?P<y>.+?)[\s,]+i\s+mean\s+(?P<x>.+)$", I), True),
]
_TRAIL = re.compile(r"[\s,.!?]+(?:please|pls|bro|yaar|na|zoha|okay|ok)?[\s,.!?]*$", I)


_SECRETS = [
    (re.compile(r"\b(?:password|passcode|pin|otp|cvv|pwd)\b\s*(?:is|:|=)?\s*\S+", I), "[secret removed]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[email]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[number removed]"),               # card / account numbers
    (re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[abp]|AIza)[-_A-Za-z0-9]{16,}\b"), "[key removed]"),  # API keys, tokens
    (re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{5,}\b"), "[token removed]"),       # JWTs
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "[key removed]"),
]


def redact(value):
    """Strip passwords, emails, card numbers and API keys before anything is written to disk."""
    if isinstance(value, str):
        for rx, rep in _SECRETS:
            value = rx.sub(rep, value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _words(s: str) -> List[str]:
    return re.findall(r"[a-z0-9][a-z0-9.+#-]*[a-z0-9]|[a-z0-9]", (s or "").lower())


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _clean_term(s: str) -> str:
    s = _TRAIL.sub("", s.strip())
    s = re.sub(r"^(?:the|a|an)\s+", "", s, flags=I)
    return s.strip(" \"'.,")


class Learner:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.dir = data_dir
        self.journal_path = data_dir / "turns.jsonl"
        self.learned_path = data_dir / "learned.json"
        self.recipes_path = data_dir / "recipes.json"
        self._lock = threading.Lock()
        self.aliases: Dict[str, str] = {}
        self.vocab: List[str] = []
        self.recipes: List[Dict] = []
        self.corpus: List[Dict] = []          # past turns for recall: {"id","t","user","reply"}
        self._df: Counter = Counter()
        self.cur: Optional[Dict] = None        # the turn in progress
        self.prev: Optional[Dict] = None       # the last finished turn
        self._load()

    # ── persistence ─────────────────────────────────────────────────────
    def _load(self):
        try:
            d = json.loads(self.learned_path.read_text(encoding="utf-8"))
            self.aliases = {k.lower(): v for k, v in d.get("aliases", {}).items()}
            self.vocab = d.get("vocab", [])
        except Exception:
            pass
        try:
            self.recipes = json.loads(self.recipes_path.read_text(encoding="utf-8"))
        except Exception:
            self.recipes = []
        try:
            lines = self.journal_path.read_text(encoding="utf-8", errors="replace").splitlines()[-6000:]
            bad = set()
            for l in lines:
                try:
                    r = json.loads(l)
                except Exception:
                    continue
                if r.get("type") == "feedback":
                    if r.get("bad"):
                        bad.add(r.get("id"))
                elif r.get("text") and r.get("reply"):
                    self._index({"id": r["id"], "t": r.get("t", 0), "user": r["text"], "reply": r["reply"]})
            self.corpus = [c for c in self.corpus if c["id"] not in bad]
        except Exception:
            pass

    def _save_learned(self):
        self._write(self.learned_path, {"aliases": self.aliases, "vocab": self.vocab})

    def _write(self, path: Path, obj):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            log.exception("could not save %s", path.name)

    def _append(self, row: Dict):
        try:
            with self._lock:
                if self.journal_path.exists() and self.journal_path.stat().st_size > 30_000_000:
                    self.journal_path.replace(self.journal_path.with_name(f"turns-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"))
                with open(self.journal_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(redact(row), ensure_ascii=False) + "\n")
        except Exception:
            log.exception("journal write failed")

    # ── vocabulary + aliases ────────────────────────────────────────────
    def stt_vocab(self, base: str) -> str:
        """Whisper prompt: the base hint plus learned words (most recent last, short enough for Whisper)."""
        extra = [w for w in dict.fromkeys(SEED_VOCAB + self.vocab[-30:]) if w.lower() not in base.lower()]
        return (base + " " + ", ".join(extra) + ".").strip()[:700]

    def apply_aliases(self, text: str) -> str:
        out = text
        for wrong, right in sorted(self.aliases.items(), key=lambda kv: -len(kv[0])):
            out = re.sub(r"(?<![A-Za-z0-9])" + re.escape(wrong) + r"(?![A-Za-z0-9])", right, out, flags=I)
        if out != text:
            log.info("Corrected words: %r → %r", text, out)
        return out

    def learn_alias(self, wrong: str, right: str):
        w, r = wrong.strip().lower(), right.strip()
        if len(_norm(w)) < 3 or w in STOP or _norm(w) == _norm(r):
            return False
        self.aliases[w] = r
        if r not in self.vocab:
            self.vocab.append(r)
        self._save_learned()
        log.info("Learned: %r means %r", w, r)
        return True

    def correction(self, text: str) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        """If `text` corrects the previous turn, returns (right, wrong_or_None, redo_text_or_None)."""
        t = text.strip().rstrip(".!?")
        for rx, has_y in _CORR:
            m = rx.match(t)
            if not m:
                continue
            x = _clean_term(m.group("x"))
            y = _clean_term(m.group("y")) if has_y else None
            if not x or len(x.split()) > 4:
                return None  # a whole new request ("I was asking you to open …") – just handle it normally
            prev = self.prev if self.prev and time.time() - self.prev.get("t", 0) < 300 else None
            ptext = prev.get("text", "") if prev else ""
            if not y and ptext:
                y = self._closest_span(ptext, x)
            if y and has_y and ptext and y.lower() not in ptext.lower():
                found = self._closest_span(ptext, y) if ptext else None
                y = found or y
            if not y:
                return None
            if not has_y and not prev:
                return None
            self.learn_alias(y, x)
            redo = None
            if ptext and re.search(re.escape(y), ptext, I):
                redo = re.sub(re.escape(y), x, ptext, count=1, flags=I)
            return x, y, redo
        return None

    @staticmethod
    def _closest_span(text: str, target: str) -> Optional[str]:
        toks = re.findall(r"\S+", text)
        nt = _norm(target)
        best, best_r = None, 0.0
        for n in (1, 2, 3):
            for i in range(len(toks) - n + 1):
                span = " ".join(toks[i:i + n]).strip(",.!?\"'")
                ns = _norm(span)
                if not ns or ns == nt or span.lower() in STOP:
                    continue
                r = difflib.SequenceMatcher(None, ns, nt).ratio()
                if r > best_r:
                    best, best_r = span, r
        if best_r >= 0.6:
            return best
        # a website the speech model mangled ("get hub" for github.com): if exactly one web address was heard, that's it
        if re.search(r"\.(?:com|in|org|net|io|ai|dev|app|co)\b", target, I):
            doms = [t.strip(",.!?\"'") for t in toks if re.search(r"\w\.(?:com|in|org|net|io|ai|dev|app|co)\b", t, I)]
            if len(doms) == 1 and _norm(doms[0]) != nt:
                return doms[0]
        return None

    # ── journal ─────────────────────────────────────────────────────────
    def begin(self, text: str, modality: str, heard: str = "", conf: Optional[float] = None):
        now = time.time()
        if self.prev and self.prev.get("id") and now - self.prev.get("t", 0) < 300 and COMPLAINT_RX.search(text):
            self.feedback(self.prev["id"], bad=True, why=text[:120])
        elif self.prev:
            self._maybe_recipe(self.prev)
        self._n = getattr(self, "_n", 0) + 1
        self.cur = {"id": f"{int(now * 1000):x}-{self._n}", "t": now, "modality": modality, "heard": heard or text, "text": text,
                    "conf": None if conf is None else round(conf, 2), "route": "", "tools": [], "flags": [], "reply": ""}

    def on_event(self, event: str, data: Dict):
        c = self.cur
        if not c:
            return
        if event == "tool_start":
            c["tools"].append({"name": data.get("name"), "args": data.get("args") or {}})
        elif event == "tool_end":
            for tl in reversed(c["tools"]):
                if tl["name"] == data.get("name") and "result" not in tl:
                    tl["result"] = str(data.get("result", ""))[:400]
                    tl["ok"] = bool(data.get("ok", True))
                    break
        elif event == "brain":
            c["route"] = "brain:" + str(data.get("name") or "")
        elif event == "reply_end":
            r = (data.get("text") or "").strip()
            if r:
                c["reply"] = (c["reply"] + " " + r).strip() if c["reply"] and r not in c["reply"] else r

    def end(self, flags: Optional[List[str]] = None, interrupted: bool = False, note: str = ""):
        c, self.cur = self.cur, None
        if not c:
            return
        c["ms"] = int((time.time() - c["t"]) * 1000)
        if not c["route"]:
            c["route"] = "parser" if c["tools"] else "control"
        c["flags"] = list(flags or []) + ([note] if note else [])
        if interrupted:
            c["interrupted"] = True
        self._append(c)
        if c["text"] and c["reply"]:
            self._index({"id": c["id"], "t": c["t"], "user": redact(c["text"]), "reply": redact(c["reply"])})
        self.prev = c

    def feedback(self, turn_id: str, bad: bool, why: str = ""):
        self._append({"type": "feedback", "id": turn_id, "bad": bad, "why": why, "t": time.time()})
        if bad:
            self.corpus = [x for x in self.corpus if x["id"] != turn_id]
            n = len(self.recipes)
            self.recipes = [r for r in self.recipes if r.get("from") != turn_id]
            if len(self.recipes) != n:
                self._write(self.recipes_path, self.recipes)
            if self.prev and self.prev.get("id") == turn_id:
                self.prev["bad"] = True

    # ── recall: keyword search over past turns ──────────────────────────
    def _index(self, item: Dict):
        terms = {w for w in _words(item["user"] + " " + item["reply"]) if w not in STOP and len(w) > 2}
        item["terms"] = terms
        self.corpus.append(item)
        self._df.update(terms)
        if len(self.corpus) > 8000:
            old = self.corpus.pop(0)
            self._df.subtract(old["terms"])

    def recall(self, query: str, before: float, k: int = 2) -> List[Dict]:
        q = {w for w in _words(query) if w not in STOP and len(w) > 2}
        if not q or not self.corpus:
            return []
        n = len(self.corpus)
        idf = {w: math.log(1 + n / (1 + self._df.get(w, 0))) for w in q}
        scored = []
        for it in self.corpus:
            if it["t"] >= before:
                continue
            hit = q & it["terms"]
            if not hit:
                continue
            s = sum(idf[w] for w in hit) / math.sqrt(len(it["terms"]) + 4)
            if min(self._df.get(w, 0) for w in hit) <= max(2, 0.25 * n):  # at least one distinctive word in common
                scored.append((s, it))
        scored.sort(key=lambda x: -x[0])
        return [it for s, it in scored[:k] if s >= 0.6]

    # ── recipes ─────────────────────────────────────────────────────────
    def _maybe_recipe(self, turn: Dict):
        tools = [t for t in turn.get("tools", []) if t.get("ok")]
        if turn.get("bad") or not turn.get("route", "").startswith("brain") or len(tools) < 2 or len(tools) != len(turn["tools"]):
            return
        steps = [{"name": t["name"], "args": redact({k: v for k, v in (t.get("args") or {}).items() if k not in ("ref", "confirmed")})}
                 for t in tools][:8]
        for r in self.recipes:
            if difflib.SequenceMatcher(None, r["text"].lower(), turn["text"].lower()).ratio() > 0.85:
                r.update(steps=steps, t=turn["t"], **{"from": turn["id"]})
                break
        else:
            self.recipes.append({"text": turn["text"], "steps": steps, "t": turn["t"], "from": turn["id"]})
        self.recipes = self.recipes[-300:]
        self._write(self.recipes_path, self.recipes)
        log.info("Saved recipe for %r (%d steps)", turn["text"][:60], len(steps))

    def recipe_for(self, text: str) -> Optional[Dict]:
        best, best_r = None, 0.0
        tw = {w for w in _words(text) if w not in STOP}
        for r in self.recipes:
            rw = {w for w in _words(r["text"]) if w not in STOP}
            if not tw or not rw:
                continue
            j = len(tw & rw) / len(tw | rw)
            s = max(j, difflib.SequenceMatcher(None, text.lower(), r["text"].lower()).ratio() * 0.9)
            if s > best_r:
                best, best_r = r, s
        return best if best_r >= 0.55 else None

    # ── what the brain gets to see ──────────────────────────────────────
    def prompt_context(self, user_text: str, memory=None) -> str:
        parts = []
        if memory is not None:
            summ = memory.summary_text()
            if summ:
                parts.append("Earlier in this conversation (summary): " + summ)
            hist = memory.recent()
            before = min((h.get("t", time.time()) for h in hist), default=time.time())
        else:
            before = time.time()
        hits = self.recall(user_text, before=before - 1)
        if hits:
            lines = [f"- {time.strftime('%d %b %H:%M', time.localtime(h['t']))} user: {h['user'][:160]!r} → you: {h['reply'][:200]!r}"
                     for h in hits]
            parts.append("Possibly relevant from earlier conversations (use only if it helps):\n" + "\n".join(lines))
        rec = self.recipe_for(user_text)
        if rec:
            steps = " → ".join(f"{s['name']}({', '.join(f'{k}={v!r}' for k, v in s['args'].items())})" for s in rec["steps"])
            parts.append(f"A similar request earlier ({rec['text'][:80]!r}) was done with these steps, which worked: {steps}. "
                         f"Reuse them if they fit (element numbers change, so read the page again).")
        known = [v for v in dict.fromkeys(self.vocab[-15:])]
        if known:
            parts.append("Words the user taught you (correct spellings): " + ", ".join(known))
        return "\n\n".join(parts)


# ── rolling summary (needs the local model; runs in the background) ─────────
def summarize(root_url: str, model: str, old_summary: str, turns: List[Dict], timeout: float = 40.0) -> str:
    import urllib.request

    convo = "\n".join(f"{'User' if t['role'] == 'user' else 'Zoha'}: {t['text'][:400]}" for t in turns)
    prompt = (f"Current summary of the conversation so far:\n{old_summary or '(none)'}\n\nMore of the conversation:\n{convo}\n\n"
              "Write the updated summary in at most 80 words: what the user is working on, decisions, names, corrected words, "
              "open tasks. Plain sentences, no lists, no preamble.")
    body = {"model": model, "stream": False, "think": False, "keep_alive": "30m",
            "messages": [{"role": "user", "content": prompt}], "options": {"temperature": 0.2, "num_predict": 160}}
    root = root_url.rstrip("/")
    root = root[:-3] if root.endswith("/v1") else root
    try:
        req = urllib.request.Request(root + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = (json.loads(r.read().decode()).get("message") or {}).get("content", "").strip()
        if txt:
            return re.sub(r"\s+", " ", txt)[:700]
    except Exception as e:
        log.info("summary via local model failed (%s) – using a plain digest", str(e)[:120])
    digest = " / ".join(t["text"][:80] for t in turns if t["role"] == "user")
    if old_summary:
        return (old_summary + " / " + digest)[-700:]
    return ("Earlier the user asked: " + digest)[-700:]


LEARN: Optional[Learner] = None


def get() -> Learner:
    global LEARN
    if LEARN is None:
        LEARN = Learner()
    return LEARN
