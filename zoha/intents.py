"""
Instant local intents — handled in milliseconds without the LLM.

Only strict, unambiguous phrasings are matched here (full-sentence regexes), so
nothing gets misrouted. Everything else goes to the brain. When the brain is
unavailable (no key / offline) `offline_route` gives a best-effort mapping.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

P = lambda s: re.compile(s, re.I)
END = r"[\s.!?]*$"

CONTROL = [
    (P(r"^(stop|cancel|never ?mind|nevermind|shut up|be quiet|quiet|silence|that'?s all|nothing)" + END), "stop"),
    (P(r"^(clear|reset|wipe) (the )?(context|conversation|chat|memory|history)" + END), "clear"),
    (P(r"^(forget (everything|the conversation)|start over|new (chat|conversation))" + END), "clear"),
    (P(r"^(?:(?:ok(?:ay)?|alright|fine|so|thanks?|thank you|cool|great)[,. ]+)*(?:(?:that'?s|that is) (?:all|it|enough)(?: for(?: (?:today|now|tonight))?)?[,. ]*)?"
       r"(?:you (?:can|may|could) (?:go to |now )?sleep(?: now)?|go (?:to )?sleep|sleep mode|stop listening|rest now|take rest|good ?night|"
       r"good ?bye|bye(?: bye)?|see (?:you|ya)(?: later| tomorrow)?|that'?s (?:all|it|enough)(?: for(?: (?:today|now|tonight))?)?)" + END), "sleep"),
    # "don't talk until I say/call you" → standby until the wake word (Whisper often hears "say" as "sing")
    (P(r"^(?:(?:ok(?:ay)?|now|so|and|alright|zoha)[,. ]+)*(please )?(do ?n[o']?t|don't|dont|never) (reply|respond|answer|talk|speak|say anything|process anything)"
       r"( to me| back)?( anymore)?( or [a-z ]+)? (until|unless|till) i (call|say|use|sing|tell|ask)\b.*$"), "sleep"),
    (P(r"^(?:(?:ok(?:ay)?|now|so|zoha)[,. ]+)*(?:please )?(?:stay|be|keep|go) (?:quiet|silent)(?:\b.{0,60})?" + END), "sleep"),
    (P(r"^only (reply|respond|answer|listen) (when|if) i (call|say) (you|your \w+|zoha)\b.*$"), "wakeonly"),
    (P(r"^(stop|turn off|disable) (the )?(follow[- ]?up|conversation mode|continuous (mode|listening))" + END), "wakeonly"),
    (P(r"^(turn on|enable) (the )?(follow[- ]?up|conversation mode)" + END + r"|^you can (reply|respond) without (your name|me calling you)" + END), "followup"),
    (P(r"^(?:exit|quit|close|shut ?down) (?:zoha|the assistant|yourself|the app)" + END + r"|^(?:exit|quit) app" + END), "exit"),
]

MEDIA_OBJ = r"(?:\s+(?:the|this|that|my))?(?:\s+(?:music|song|video|track|playback|youtube|spotify|audio|it))?"
MEDIA_WHERE = r"(?:\s+(?:that'?s\s+|which is\s+|currently\s+)?playing)?(?:\s+(?:over|on|in)\s+(?:the\s+)?(?:youtube|spotify|browser|chrome|edge|laptop|pc|computer))?"
BR = r"(?:\s+(?:in|on|using|with|over)\s+(?:the\s+|your\s+|my\s+|zoha'?s\s+)?(?:own\s+|playwright\s+)?browser)"
VID = r"(?:\s+(?:the|this))?(?:\s+(?:video|youtube|player|movie))?"
FAST = [
    # Zoha's own (Playwright) browser
    (P(r"^(?:open|start|launch|fire up|bring up)\s+(?:the\s+|your\s+|a\s+)?(?:own\s+)?(?:web\s+)?browser" + END), "browser_open",
     lambda m: {"target": "https://www.google.com"}),
    (P(r"^(?:open|start|launch)\s+(?:the\s+|your\s+)?browser\s+and\s+(?:go to|open|search(?: for)?)\s+(.+?)" + END), "browser_open",
     lambda m: {"target": m.group(1)}),
    (P(r"^(?:search|google|look up)(?:\s+for)?\s+(.+?)" + BR + END), "browser_open", lambda m: {"target": m.group(1)}),
    (P(r"^(?:open|go to)\s+(.+?)" + BR + END), "browser_open", lambda m: {"target": m.group(1)}),
    (P(r"^(?:start|open|launch)\s+(?:the\s+|your\s+)?browser\s+and\s+play\s+(.+?)" + END), "play_youtube",
     lambda m: {"query": m.group(1), "where": "browser"}),
    (P(r"^play\s+(.+?)" + BR + END), "play_youtube", lambda m: {"query": m.group(1), "where": "browser"}),
    (P(r"^(?:close|quit|exit)\s+(?:the\s+|your\s+)?(?:own\s+|playwright\s+)?browser" + END), "browser_close", lambda m: {}),
    (P(r"^(?:open|go to)\s+youtube" + BR + r"\s+and\s+play\s+(.+?)" + END), "play_youtube", lambda m: {"query": m.group(1), "where": "browser"}),
    # video in Zoha's browser
    (P(r"^(?:make|put|turn|set)" + VID + r"\s+(?:in(?:to)?\s+|to\s+)?full\s?screen(?: mode)?" + END +
       r"|^full\s?screen" + VID + END + r"|^(?:go|enter) full\s?screen" + END +
       r"|^(?:click|press)(?: the)? full\s?screen(?: button)?.*$"), "browser_video", lambda m: {"action": "fullscreen"}),
    (P(r"^(?:exit|leave|close|quit|get out of)(?: the)? full\s?screen" + END), "browser_video", lambda m: {"action": "exit_fullscreen"}),
    (P(r"^skip(?: the)? ads?" + END), "browser_video", lambda m: {"action": "skip_ad"}),
    (P(r"^(?:forward|skip ahead|fast forward)(?: by)? (\d+) ?(?:s|sec|secs|seconds)" + END), "browser_video",
     lambda m: {"action": "forward", "seconds": float(m.group(1))}),
    (P(r"^(?:go back|rewind|back)(?: by)? (\d+) ?(?:s|sec|secs|seconds)" + END), "browser_video",
     lambda m: {"action": "back", "seconds": float(m.group(1))}),
    (P(r"^(?:maximi[sz]e|full\s?screen)(?: the| your)?(?: own)? browser(?: window)?" + END + r"|^make(?: the| your)? browser (?:full\s?screen|maximi[sz]ed|bigger)" + END),
     "browser_window", lambda m: {"state": "maximize"}),
    (P(r"^minimi[sz]e(?: the| your)?(?: own)? browser(?: window)?" + END), "browser_window", lambda m: {"state": "minimize"}),
    (P(r"^(?:pause|hold)" + MEDIA_OBJ + MEDIA_WHERE + END), "media_control", lambda m: {"action": "pause"}),
    (P(r"^(?:stop|end)" + r"(?:\s+(?:the|this|that|my))?\s+(?:music|song|video|track|playback|youtube|audio)" + MEDIA_WHERE + END),
     "media_control", lambda m: {"action": "stop"}),
    (P(r"^(?:resume|unpause|continue|play)" + MEDIA_OBJ + r"(?:\s+again)?" + MEDIA_WHERE + END), "media_control", lambda m: {"action": "play"}),
    (P(r"^(?:next|skip)(?:\s+(?:the|this))?(?:\s+(?:song|track|one|video))?" + MEDIA_WHERE + END), "media_control", lambda m: {"action": "next"}),
    (P(r"^(?:previous|go back|last|play the previous)(?:\s+(?:song|track|one|video))?" + MEDIA_WHERE + END), "media_control", lambda m: {"action": "previous"}),
    (P(r"^(?:what(?:'?s| is)(?: this| the)? (?:song|playing|music|video)(?: playing| called| is this)?|what song is (?:this|playing))" + END),
     "media_control", lambda m: {"action": "status"}),
    (P(r"^(?:the )?(?:video|song|music)(?: is| isn'?t| is not)(?: still)? (?:not )?(?:stopped|paused)" + END), "media_control", lambda m: {"action": "pause"}),
    (P(r"^(?:it'?s|the (?:video|song|music) is) still playing" + END), "media_control", lambda m: {"action": "pause"}),
    (P(r"^(volume|turn it) up" + END), "set_volume", lambda m: {"change": "up"}),
    (P(r"^(volume|turn it) down" + END), "set_volume", lambda m: {"change": "down"}),
    (P(r"^(mute|unmute)( (the )?(volume|sound|audio|pc|computer))?" + END), "set_volume", lambda m: {"change": "mute"}),
    (P(r"^(set )?(the )?volume (to )?(\d{1,3})( ?%| percent)?" + END), "set_volume", lambda m: {"level": int(m.group(4))}),
    (P(r"^what('?s| is) the time( now)?" + END + r"|^what time is it( now)?" + END), "get_datetime", lambda m: {}),
    (P(r"^(take a )?screenshot" + END), "take_screenshot", lambda m: {}),
    (P(r"^lock (my |the )?(pc|computer|screen|laptop)" + END), "lock_pc", lambda m: {}),
    (P(r"^cancel (the )?(shutdown|restart)" + END), "power", lambda m: {"action": "cancel", "confirmed": True}),
]

OFFLINE = [
    (P(r"^(?:open|launch|start|run)\s+(.+?)" + END), "open_app", lambda m: {"name": m.group(1)}),
    (P(r"^(?:close|quit|exit|kill)\s+(.+?)" + END), "close_app", lambda m: {"name": m.group(1)}),
    (P(r"^play\s+(.+?)\s+on\s+spotify" + END), "play_spotify", lambda m: {"query": m.group(1)}),
    (P(r"^play\s+(.+?)(?:\s+(?:on|over|in)\s+(?:the\s+)?youtube)?" + END), "play_youtube", lambda m: {"query": m.group(1)}),
    (P(r"^(?:google|search(?: google| the web)?(?: for)?)\s+(.+?)" + END), "web_search", lambda m: {"query": m.group(1)}),
    (P(r"^(?:take a note|note down|make a note|note)\s*:?\s+(.+?)" + END), "create_note", lambda m: {"text": m.group(1)}),
    (P(r"^set (?:a )?timer (?:for )?(\d+(?:\.\d+)?)\s*(minutes?|mins?|seconds?|secs?)" + END), "set_timer",
     lambda m: {"minutes": float(m.group(1))} if m.group(2).lower().startswith("m") else {"seconds": float(m.group(1))}),
    (P(r"^(?:what'?s the )?weather(?: in (.+?))?(?: today)?" + END), "get_weather", lambda m: {"city": m.group(1)} if m.group(1) else {}),
    (P(r"^(?:system status|system stats|how'?s my (?:pc|computer|system))" + END), "system_status", lambda m: {}),
    (P(r"^(?:remember|note) that\s+(.+?)" + END), "remember", lambda m: {"fact": m.group(1)}),
]


def _clean(text: str) -> str:
    t = text.strip().strip(",. ?!")
    for _ in range(3):
        t = re.sub(r"^(?:(?:hey|hi|ok|okay|yo|um+|uh+|hmm+)[, ]+)?(?:zoha|jarvis)\b[,.!? ]*", "", t, flags=re.I)
        t = re.sub(r"^(please|can you|could you|would you)\s+", "", t, flags=re.I)
        t = re.sub(r"[, ]+(?:zoha|jarvis|bro|yaar|na|please|for me|now)" + END, "", t, flags=re.I)
        t = t.strip(",. ?!")
    return t.strip()


def control(text: str) -> Optional[str]:
    t = _clean(text)
    for rx, name in CONTROL:
        if rx.match(t):
            return name
    return None


BROWSER_PHRASE = re.compile(
    r"\s*\b(?:over|on|in|inside|using|with|through|via|into)\s+(?:the\s+|your\s+|my\s+|zoha'?s\s+|a\s+)?"
    r"(?:own\s+|playwright\s+|controlled\s+|new\s+)*(?:web\s+)?browser\b", re.I)
YOUTUBE_PHRASE = re.compile(r"\s*\b(?:over|on|in|from|at|via|using|through)\s+(?:the\s+)?you\s?tube\b", re.I)
PLAY_START = re.compile(r"(?:^|\band\s+(?:then\s+)?|\bthen\s+|,\s*|^(?:(?:hey|hi|ok|okay)\s+)?(?:zoha|jarvis)[,\s]+|^(?:please|now|just)\s+|\b(?:browser|you\s?tube)[,\s]+)(?:play|put on|start playing|play me)\s+(.+)$", re.I)
JUST_MEDIA = re.compile(r"^(?:it|this|that|music|the music|the song|the video|video|song|again|it again|the track|"
                        r"something|anything|youtube|the youtube)$", re.I)


def parse_play(text: str) -> Optional[Tuple[str, dict]]:
    """Understand 'play …' however it's phrased. Word order doesn't matter:
    'Play the song middle of the night over the playwright browser over the YouTube'
      → play_youtube(query='middle of the night', where='browser')"""
    t = _clean(text)
    m = PLAY_START.search(t)
    if not m:
        return None
    q = m.group(1)
    where = "browser" if re.search(r"\bbrowser\b", t, re.I) else "default"
    q = BROWSER_PHRASE.sub(" ", q)
    q = YOUTUBE_PHRASE.sub(" ", q)
    q = re.sub(r"\s+(?:for me|please|now|right now)\b", " ", q, flags=re.I)
    q = re.sub(r"\s+", " ", q).strip(" ,.!?")
    from .tools import clean_media_query

    q = clean_media_query(q)
    if not q or JUST_MEDIA.match(q) or q.lower() == "music":
        return None  # "play it / play the video" → resume, handled by media control
    return ("play_youtube", {"query": q, "where": where})


def fast_route(text: str) -> Optional[Tuple[str, dict]]:
    t = _clean(text)
    # 1) media control ("play it", "pause the video") wins over song search
    for rx, tool, args in FAST:
        if tool == "media_control":
            m = rx.match(t)
            if m:
                return tool, args(m)
    # 2) any "play <something>" request, whatever the word order
    hit = parse_play(t)
    if hit:
        return hit
    for rx, tool, args in FAST:
        m = rx.match(t)
        if m:
            return tool, args(m)
    return None


def offline_route(text: str) -> Optional[Tuple[str, dict]]:
    hit = fast_route(text)
    if hit:
        return hit
    t = _clean(text)
    for rx, tool, args in OFFLINE:
        m = rx.match(t)
        if m:
            return tool, args(m)
    return None
