"""
Wake-word matching on transcripts.

Accepts the wake word at the START ("Zoha, open Spotify", "Hey Zoha ...") or the END
("open Spotify, Zoha"). Uses a curated list of real Whisper misspellings of "Zoha"
plus fuzzy matching for custom wake words. Deliberately does NOT accept loose
phrases like "see ya" / "assistant" that caused false triggers in v1.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import List, Optional

FILLERS = {"hey", "hi", "hello", "ok", "okay", "yo", "oi", "oh", "uh", "um", "so", "and", "a", "please"}

# How Whisper actually spells "Zoha" across accents (validated against TTS + real voices)
VARIANTS = {
    "zoha": {"zoha", "zoya", "zoa", "zowa", "zuha", "zouha", "zoah", "zohah", "zohha", "zoha's", "zohas", "soha", "joha", "zoher"},
    "jarvis": {"jarvis", "jarves", "jarvus", "jervis", "jarviss", "javis"},
}

# "Hey Zoha" fused into one token by Whisper (only valid as the FIRST word)
FUSED_HEY = {
    "zoha": {"hazoha", "hizoha", "hezoha", "heyzoha", "hayzoha", "hasoha", "azoha", "hazoya", "hezoya", "heyzoya", "hayzoya", "hasoya", "hazuha", "hezuha", "heyzuha"},
}

# Single-token variants that are common English words → only accepted as a
# standalone wake (not glued into a sentence) or right after a filler like "hey".
RISKY = {"soha", "joha", "zoa", "zowa", "zoher"}


def _norm(text: str) -> List[str]:
    """Lower-cased tokens aligned 1:1 with _orig_tokens()."""
    out = []
    for w in _orig_tokens(text):
        w = w.lower().replace("’", "'")
        w = re.sub(r"[^a-z0-9']", "", w).strip("'")
        out.append(w)
    return out


@dataclass
class WakeResult:
    matched: str
    command: str  # remainder (may be "")
    position: str  # 'start' | 'end' | 'only'


class WakeMatcher:
    def __init__(self, words: List[str]):
        self.words = [w.lower().strip() for w in words if w.strip()]

    def _variants(self, word: str):
        return VARIANTS.get(word, {word})

    def _tok_match(self, tok: str, word: str) -> bool:
        if tok in self._variants(word):
            return True
        if len(word) >= 5:  # fuzzy only for longer custom words
            return difflib.SequenceMatcher(None, tok, word).ratio() >= 0.8
        return False

    def match(self, text: str) -> Optional[WakeResult]:
        toks = _norm(text)
        if not toks:
            return None
        for word in self.words:
            wt = word.split()
            n = len(wt)

            def hit(seq):
                return len(seq) == n and all(self._tok_match(a, b) for a, b in zip(seq, wt))

            # START (fused "Hey Zoha" → "Hasia")
            if n == 1 and toks[0] in FUSED_HEY.get(word, ()):
                rest = toks[1:]
                return WakeResult(word, _rest(text, 1), "only" if not rest else "start")
            # START: skip up to 2 fillers ("hey", "ok")
            i = 0
            while i < len(toks) and i < 2 and toks[i] in FILLERS:
                i += 1
            had_filler = i > 0
            if hit(toks[i : i + n]):
                rest = toks[i + n :]
                tok = toks[i]
                if tok in RISKY and not had_filler and len(rest) > 0 and rest[0] not in ("open", "play", "what", "whats", "what's", "tell", "set", "search", "can", "could", "please", "turn", "close", "stop", "pause", "take", "remind", "how", "who", "start", "launch", "show", "find", "check", "are", "is", "do", "i"):
                    continue
                return WakeResult(word, _rest(text, i + n), "only" if not rest else "start")
            # END: "..., Zoha"
            if len(toks) > n and hit(toks[-n:]):
                if toks[-n] in RISKY:
                    continue
                cmd = " ".join(_orig_tokens(text)[: len(toks) - n])
                return WakeResult(word, cmd.strip(" ,.!?"), "end")
        return None


def _orig_tokens(text: str) -> List[str]:
    return [w for w in re.split(r"\s+", text.strip()) if re.sub(r"[^A-Za-z0-9']", "", w)]


def _rest(text: str, n_skip: int) -> str:
    """Remainder of the ORIGINAL text after the first n_skip word tokens (keeps casing/punctuation)."""
    toks = _orig_tokens(text)
    rest = " ".join(toks[n_skip:])
    return re.sub(r"^[\s,.!?:;-]+", "", rest).strip()
