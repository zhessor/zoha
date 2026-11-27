"""
Zoha's command understanding (no LLM, instant, deterministic).

parse(text, ctx) → list of Action(tool, args, soft) or [] when it's not a plain command.

How it works (word order doesn't matter):
  1. normalise: drop wake words, politeness ("can you", "please", "for me") and punctuation
  2. lift modifiers out wherever they are: "in the browser", "on/over the YouTube", "on Spotify"
  3. split compound requests: "open VS Code and play some lofi" → two commands
  4. each command = action word (+ synonyms) + object + details → one tool call
  5. anything not clearly understood → [] → the LLM handles it

soft=True means "best guess" (e.g. an app name): if the tool fails, the LLM gets a go instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

I = re.I


@dataclass
class Action:
    tool: str
    args: Dict = field(default_factory=dict)
    soft: bool = False


@dataclass
class Ctx:
    browser_open: bool = False
    browser_url: str = ""


# ── normalisation ────────────────────────────────────────────────────────────
LEAD = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay|yo)\s+)?(?:zoha|jarvis|zoya|soha|zuha|zouha)\b[\s,.:!-]*|"
    r"^(?:(?:can|could|would|will) you(?: please)?|please|kindly|just|now|ok(?:ay)?|so|alright|hey|"
    r"i (?:want|need|would like) (?:you )?to|i'?d like (?:you )?to|let'?s|go ahead and|do me a favou?r and|"
    r"um+|uh+|hmm+|listen|do one thing|yo|bro|bhai|yaar|quickly|quick|actually)\b[\s,]*", I)
TRAIL = re.compile(r"[\s,]*\b(?:please|pls|plz|for me|right now|now|thanks|thank you|okay|ok|zoha|jarvis|real quick|quickly|"
                   r"right away|asap|fast|jaldi|bro|bhai|yaar|yar|na|naa|re|man|dude|buddy)\s*\??$", I)

BROWSER_MOD = re.compile(r"\s*\b(?:over|on|in|inside|using|with|through|via|into)\s+(?:the\s+|your\s+|my\s+|zoha'?s\s+|a\s+)?"
                         r"(?:own\s+|playwright\s+|controlled\s+|new\s+)*(?:web\s+)?browser\b", I)
YOUTUBE_MOD = re.compile(r"\s*\b(?:over|on|in|from|at|via|using|through)\s+(?:the\s+)?you\s?tube\b", I)
SPOTIFY_MOD = re.compile(r"\s*\b(?:over|on|in|from|using|through)\s+(?:the\s+)?spotify\b", I)
LAPTOP_MOD = re.compile(r"\s*\b(?:on|in|over)\s+(?:my|the)\s+(?:laptop|pc|computer|system|desktop)\b", I)


MISHEARD = [
    (r"\b(?:playland|play land|play ?right|play ?wright|play ?write|playwrite|plywood|period|play red|pay right)(?=\s+browser\b)", "playwright"),
    (r"\b(?:skim|skit|skid|skeep|skips)\b(?=\s+(?:the\s+|this\s+|that\s+)?(?:ad|ads|add|adds|advert|advertisement)\b)", "skip"),
    (r"\b(?:the\s+)?(?:add|adds)\b(?=\s*$)", "the ad"),
    (r"\b(?:radius|race|rays|raids|rise|raze)\b(?=\s+(?:the\s+)?(?:volume|sound))", "raise"),
    (r"\b(?:paws|pours|pose|porz)\b(?=\s+(?:the\s+)?(?:song|music|video|it)\b)", "pause"),
    (r"\bfull\s*-\s*screen\b", "full screen"),
    (r"\bda\b(?=\s+[a-z])", "the"),          # Whisper hears "the" as "da"
    (r"\bnote pad\b", "notepad"), (r"\bvs court\b", "vs code"), (r"\byou tube\b", "youtube"), (r"\bspotty fy\b", "spotify"),
]


def normalise(text: str) -> str:
    t = text.strip().replace("’", "'")
    for rx, rep in MISHEARD:
        t = re.sub(rx, rep, t, flags=I)
    t = re.sub(r"[“”\"]", "", t)
    t = re.sub(r"\s+", " ", t).strip(" .!?,")
    for _ in range(4):
        new = LEAD.sub("", t).strip(" ,")
        new = TRAIL.sub("", new).strip(" ,.!?")
        if new == t:
            break
        t = new
    return t


# ── vocab ────────────────────────────────────────────────────────────────────
MEDIA_OBJ = r"(?:the |this |that |my |current )?(?:music|song|songs|video|track|playback|audio|it|youtube|spotify|player|movie|clip)?"
MEDIA_WORDS = {"", "it", "this", "that", "music", "the music", "song", "the song", "the video", "video", "the track", "track",
               "playback", "audio", "the audio", "youtube", "the youtube", "spotify", "the player", "player", "this song",
               "this video", "that song", "that video", "my music", "current song", "the current song", "the movie", "movie"}
KNOWN_APPS = {a.strip() for a in """notepad|calculator|calc|chrome|google chrome|edge|microsoft edge|firefox|brave|opera|spotify|discord|
whatsapp|telegram|word|microsoft word|excel|microsoft excel|powerpoint|ppt|outlook|onenote|teams|microsoft teams|zoom|vs code|vscode|
visual studio code|visual studio|file explorer|explorer|settings|control panel|task manager|paint|snipping tool|camera|photos|clock|
alarms|microsoft store|store|steam|epic games|obs|obs studio|vlc|media player|postman|figma|notion|obsidian|slack|blender|unity|
unity hub|intellij|intellij idea|pycharm|eclipse|android studio|windsurf|cursor|docker|docker desktop|github desktop|mongodb compass|
compass|command prompt|cmd|powershell|terminal|windows terminal|git bash|anaconda|jupyter|canva|photoshop|premiere pro|after effects|
davinci resolve|filmora|audacity|calendar app|mail app|word pad|wordpad|sticky notes|recorder|voice recorder|xbox|minecraft|valorant|
riot client|whatsapp desktop""".replace("\n", "").split("|")}
KNOWN_FOLDERS = {"downloads", "download", "documents", "document", "desktop", "pictures", "photos", "videos", "music",
                 "screenshots", "home"}
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "twenty five": 25, "thirty": 30, "forty": 40,
           "forty five": 45, "fifty": 50, "sixty": 60, "ninety": 90, "a": 1, "an": 1, "half an": 0.5, "a couple of": 2, "couple of": 2}


def _num(s: str) -> Optional[float]:
    s = s.strip().lower()
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return float(s)
    return float(NUMBERS[s]) if s in NUMBERS else None


NUM = r"(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty(?: five)?|thirty|forty(?: five)?|fifty|sixty|ninety|a couple of|half an|an|a)"


CLOCK = r"(\d{1,2}(?:[:.]\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?|\d{3,4}\s*(?:a\.?m\.?|p\.?m\.?)?|noon|midnight)"


def _clock(s: str) -> Optional[str]:
    """Clock words are passed through for set_reminder to resolve (it picks the next a.m./p.m. occurrence)."""
    s = s.strip()
    return s if re.fullmatch(CLOCK, s, I) else None


def _clock_old(s: str) -> Optional[str]:
    """'6 pm' / '6:30 p.m.' / '18:00' / 'noon' / 'midnight' → 'HH:MM'."""
    s = s.lower().replace(".", "").strip()
    if s in ("noon", "midday"):
        return "12:00"
    if s == "midnight":
        return "00:00"
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if not ap and not m.group(2) and h <= 7:
        h += 12  # "at 6" for a reminder almost always means the evening
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


# ── command handlers (each returns Action | None) ────────────────────────────
def _media(t: str, ctx: Ctx, flags) -> Optional[Action]:
    def obj_ok(rest: str) -> bool:
        rest = re.sub(r"\b(?:that'?s|which is|currently|still)?\s*playing\b", "", rest, flags=I).strip()
        rest = re.sub(r"^(?:the|this|that|my)\s+", "", rest.strip(), flags=I)
        return rest.lower() in {w.replace("the ", "") for w in MEDIA_WORDS} or rest == ""

    where_video = "browser_video" if (flags["browser"] or ("youtube.com" in ctx.browser_url)) else None
    m = re.fullmatch(r"(pause|hold|freeze)\s*(.*)", t, I)
    if m and obj_ok(m.group(2)):
        return Action("media_control", {"action": "pause"})
    m = re.fullmatch(r"(stop|end|kill)\s+(.*)", t, I)
    if m and obj_ok(m.group(2)) and m.group(2).strip():
        return Action("media_control", {"action": "stop"})
    m = re.fullmatch(r"(resume|unpause|continue|play|start)\s*(.*?)(?:\s+again)?", t, I)
    app_like = m and re.sub(r"^(?:the)\s+", "", m.group(2).strip().lower()) in ("youtube", "spotify")
    if m and obj_ok(m.group(2)) and not app_like and not (m.group(1).lower() == "start" and not m.group(2)):
        return Action("media_control", {"action": "play"})
    if re.fullmatch(r"skip(?: (?:that|it|this|this one|that one))?", t, I) and "youtube.com" in ctx.browser_url:
        return Action("browser_video", {"action": "skip"})  # skips the ad if one is showing, otherwise next video
    if re.fullmatch(r"(?:play\s+)?(?:the\s+)?(?:next|skip)(?:\s+(?:to the next|this|the|that|it))?(?:\s+(?:song|track|one|video))?", t, I) \
            or re.fullmatch(r"skip(?: this| the)? (?:song|track|video)", t, I) or t.lower() == "skip":
        return Action("media_control", {"action": "next"})
    if re.fullmatch(r"(?:play\s+)?(?:the\s+)?(?:previous|last|prior)(?:\s+(?:song|track|one|video))?|go back (?:a|one) (?:song|track)", t, I):
        return Action("media_control", {"action": "previous"})
    if re.fullmatch(r"(?:what(?:'?s| is)(?: this| the)?(?: current)? (?:song|track|music|video|playing)(?: playing| called| is this| name)?"
                    r"|what song is (?:this|playing)|what(?:'?s| is) playing(?: right now)?|which song is this|name (?:of )?this song)", t, I):
        return Action("media_control", {"action": "status"})
    if re.fullmatch(r"(?:the |this |it'?s |it is )?(?:video|song|music|it|youtube)?\s*(?:is|isn'?t|is not|'s)?\s*(?:still )?"
                    r"(?:not )?(?:stopped|paused|playing)(?: still)?", t, I) and re.search(r"(still|n'?t|not)", t, I):
        return Action("media_control", {"action": "pause"})
    return None


def _video(t: str, ctx: Ctx, flags) -> Optional[Action]:
    cap = r"(?:the )?(?:captions?|subtitles?|cc|closed captions?|subs)"
    if re.fullmatch(r"(?:turn|switch|put|toggle)(?: the)? (?:captions?|subtitles?|cc|closed captions?|subs) off|(?:turn|switch) off " + cap +
                    r"|(?:hide|remove|disable|close|stop|kill|get rid of) " + cap + r"|no " + cap + r"(?: please)?|" + cap + r" off(?: please)?", t, I):
        return Action("browser_video", {"action": "captions_off"}) if ctx.browser_open else None
    if re.fullmatch(r"(?:turn|switch|put)(?: the)? (?:captions?|subtitles?|cc|closed captions?|subs) on|(?:turn|switch) on " + cap +
                    r"|(?:show|enable|add|display) " + cap + r"|" + cap.replace("(?:the )?", "") + r"(?: on)?(?: please)?", t, I):
        return Action("browser_video", {"action": "captions_on"}) if ctx.browser_open else None
    if re.fullmatch(r"(?:restart|replay|rewind)(?: the| this)?(?: video| song)?(?: from the (?:beginning|start))?|"
                    r"(?:start|play)(?: the| this| it)?(?: video| song)? (?:from|over from|again from) (?:the )?(?:beginning|start|zero|0)|"
                    r"(?:start|play) (?:it|the video|this|the song) (?:over|again)|go (?:back )?to the (?:beginning|start)(?: of the video)?", t, I):
        return Action("browser_video", {"action": "restart"}) if ctx.browser_open else Action("media_control", {"action": "previous"}, soft=True)
    if ctx.browser_open:
        m = re.fullmatch(r"(?:go|jump|skip|seek|move|take me)(?: ahead| forward| back)? to (?:the )?(\d{1,3})(?:[:.](\d{2}))?"
                         r" ?(minutes?|mins?|minute mark|min mark|seconds?|secs?|mark)?(?: mark)?(?: in| of)?(?: the video)?", t, I)
        if m and (m.group(2) or m.group(3)):
            a, b, unit = int(m.group(1)), m.group(2), (m.group(3) or "").lower()
            secs = a * 60 + int(b) if b else (a if unit.startswith("sec") else a * 60)
            return Action("browser_video", {"action": "seek", "value": secs})
        sp = {"double speed": 2, "2x": 2, "2x speed": 2, "speed up": 1.5, "speed it up": 1.5, "faster": 1.5, "slow down": 0.75,
              "slower": 0.75, "half speed": 0.5, "normal speed": 1, "normal": 1}
        m = re.fullmatch(r"(?:play|set|make|put)?(?: it| the video| this)?(?: at| to)? ?(double speed|2x speed|2x|speed up|speed it up|faster|"
                         r"slow down|slower|half speed|normal speed)(?: the video| it)?(?: speed)?", t, I)
        if m:
            return Action("browser_video", {"action": "speed", "value": sp[m.group(1).lower()]})
        if re.fullmatch(r"(?:make it |go back to )?small screen|(?:make (?:it|the video) )?smaller", t, I) and "youtube.com" in ctx.browser_url:
            return Action("browser_video", {"action": "exit_fullscreen"})
    if re.search(r"\bfull\s?screen\b", t, I):
        if re.search(r"\b(exit|leave|close|quit|out of|get out|stop|remove|turn off)\b", t, I):
            return Action("browser_video", {"action": "exit_fullscreen"})
        if re.search(r"\b(browser|window)\b", t, I) and not re.search(r"\b(video|youtube|player)\b", t, I):
            return Action("browser_window", {"state": "maximize"})
        return Action("browser_video", {"action": "fullscreen"})
    if re.fullmatch(r"(?:exit|leave|close)\s+full\s?screen.*", t, I):
        return Action("browser_video", {"action": "exit_fullscreen"})
    if re.fullmatch(r"(?:skip|close|remove|get rid of)(?: the| this| that)? (?:ads?|adverts?|advertisements?)(?: please)?", t, I):
        return Action("browser_video", {"action": "skip_ad"})
    m = re.fullmatch(r"(?:skip ahead|fast forward|forward|go forward|jump ahead|move ahead)(?: the video)?(?: by)? " + NUM +
                     r" ?(seconds?|secs?|s|minutes?|mins?)", t, I)
    if m:
        n = _num(m.group(1)) or 10
        return Action("browser_video", {"action": "forward", "seconds": n * (60 if m.group(2).lower().startswith("m") else 1)})
    m = re.fullmatch(r"(?:rewind|go back|back|jump back|skip back)(?: the video)?(?: by)? " + NUM + r" ?(seconds?|secs?|s|minutes?|mins?)", t, I)
    if m:
        n = _num(m.group(1)) or 10
        return Action("browser_video", {"action": "back", "seconds": n * (60 if m.group(2).lower().startswith("m") else 1)})
    m = re.fullmatch(r"(?:set |change )?(?:the )?(?:playback |video )?speed(?: to)? (\d(?:\.\d+)?)x?|play (?:it )?at (\d(?:\.\d+)?)x(?: speed)?", t, I)
    if m:
        return Action("browser_video", {"action": "speed", "value": float(m.group(1) or m.group(2))})
    if re.fullmatch(r"(?:mute|unmute) the (?:video|youtube|tab)", t, I):
        return Action("browser_video", {"action": t.split()[0].lower()})
    if re.fullmatch(r"(?:maximi[sz]e|enlarge)(?: the| your| my)?(?: own)? (?:browser|window)(?: window)?|make (?:the |your )?browser (?:bigger|maximi[sz]ed)", t, I):
        return Action("browser_window", {"state": "maximize"})
    if re.fullmatch(r"minimi[sz]e(?: the| your| my)?(?: own)? (?:browser|window)(?: window)?|hide (?:the |your )?browser", t, I):
        return Action("browser_window", {"state": "minimize"})
    if re.fullmatch(r"restore(?: the| your)? browser(?: window)?", t, I):
        return Action("browser_window", {"state": "restore"})
    return None


def _volume(t: str) -> Optional[Action]:
    m = re.fullmatch(r"turn (?:the |it |that )?(?:volume |sound |music )?(up|down)(?: (?:the )?(?:volume|sound))?(?: a (?:bit|little|lot))?", t, I)
    if m:
        return Action("set_volume", {"change": m.group(1).lower()})
    if re.fullmatch(r"(?:raise|increase) (?:the )?(?:volume|sound)(?: a bit| a little)?", t, I):
        return Action("set_volume", {"change": "up"})
    if re.fullmatch(r"(?:turn |make it |volume |sound )?(?:up|louder)(?: (?:the )?(?:volume|sound|it|music))?(?: a bit| a little)?|"
                    r"(?:increase|raise|turn up|bump up) (?:the )?(?:volume|sound)(?: a bit| a little)?|(?:volume|sound) up(?: a bit)?|louder", t, I):
        return Action("set_volume", {"change": "up"})
    if re.fullmatch(r"(?:turn |make it |volume |sound )?(?:down|quieter|softer)(?: (?:the )?(?:volume|sound|it|music))?(?: a bit| a little)?|"
                    r"(?:decrease|lower|reduce|turn down) (?:the )?(?:volume|sound)(?: a bit| a little)?|(?:volume|sound) down(?: a bit)?|quieter|softer", t, I):
        return Action("set_volume", {"change": "down"})
    m = re.fullmatch(r"(?:set |change |put |turn |raise |increase |lower |decrease |reduce |bring |make )?(?:the )?(?:system )?(?:volume|sound)"
                     r"(?: level)?(?: up| down)? (?:to |at |by )?(\d{1,4})(?: ?%| percent)?|volume (\d{1,4})", t, I)
    if m:
        return Action("set_volume", {"level": int(m.group(1) or m.group(2))})
    m = re.fullmatch(r"(mute|unmute)(?: the)?(?: (?:volume|sound|audio|pc|computer|laptop|speakers|system|everything))?", t, I)
    if m:
        return Action("set_volume", {"change": m.group(1).lower()})
    return None


def _play(t: str, ctx: Ctx, flags) -> Optional[Action]:
    m = re.fullmatch(r"(?:play|put on|start playing|play me|queue up|blast)\s+(.+)", t, I)
    if not m:
        return None
    q = m.group(1)
    q = re.sub(r"\s+(?:for me|please|now|right now|again)\b", " ", q, flags=I)
    q = re.sub(r"\s+", " ", q).strip(" ,.!?")
    from .tools import clean_media_query

    q = clean_media_query(q)
    if not q or q.lower() in MEDIA_WORDS or q.lower() in ("music", "something", "anything"):
        return None
    if flags["spotify"]:
        return Action("play_spotify", {"query": q})
    return Action("play_youtube", {"query": q, "where": "browser" if flags["browser"] else "default"})


MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
MON = r"(" + "|".join(MONTHS) + r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"


def _calendar(t: str, ctx: Ctx, flags) -> Optional[Action]:
    if not re.search(r"\bcalendar\b", t, I):
        return None
    m = re.search(MON + r"(?:\s+(\d{4}))?", t, I)
    if re.search(r"\b(?:add|create|schedule|book|make|new) (?:an? )?(?:event|meeting|appointment)\b", t, I):
        return None  # creating events needs the LLM + browser
    if not m:
        if re.fullmatch(r"(?:open|show|go to|pull up|check)\s+(?:my |the )?(?:google )?calendar", t, I):
            return Action("browser_open", {"target": "https://calendar.google.com"})
        return None
    import datetime as _dt

    mon = next(i for i, name in enumerate(MONTHS, 1) if name.startswith(m.group(1).lower()[:3]))
    today = _dt.date.today()
    year = int(m.group(2)) if m.group(2) else (today.year if mon >= today.month else today.year + 1)
    return Action("browser_open", {"target": f"https://calendar.google.com/calendar/r/month/{year}/{mon}/1"})


def _is_site(low: str) -> Optional[str]:
    """'linkedin', 'the leetcode website', 'zomato.com' → the site name; None if it isn't one."""
    from .tools import SITES

    name = re.sub(r"\s+(?:website|web site|site|webpage|page|dot com)$", "", low).strip()
    if re.search(r"\.(?:com|in|org|net|io|ai|dev|app|co|me|gov|edu|so)\b", name) or name in SITES or name.removesuffix(".com") in SITES:
        return name
    if low != name:  # said "website" explicitly
        return name
    return None


def _known_app(low: str) -> bool:
    """Curated apps only (not the Windows Start-menu index, which also lists website shortcuts like YouTube)."""
    name = re.sub(r"\s+(?:app|application|software|program)$", "", low).strip()
    if name in KNOWN_APPS:
        return True
    try:
        from .tools import APP_ALIASES
        return name in APP_ALIASES
    except Exception:
        return False


def _is_app(low: str) -> bool:
    name = re.sub(r"\s+(?:app|application|software|program)$", "", low).strip()
    if name in KNOWN_APPS:
        return True
    try:
        from .tools import APPS, APP_ALIASES, WIN

        if name in APP_ALIASES:
            return True
        return bool(WIN and APPS.apps and APPS.find(name))
    except Exception:
        return False


def _folder(low: str) -> Optional[str]:
    f = re.sub(r"^(?:my\s+the|my|the)\s+", "", re.sub(r"\s+folder$", "", low)).strip()
    low = re.sub(r"^my\s+the\s+", "the ", low)
    if f in KNOWN_FOLDERS and not (f in KNOWN_APPS and not re.search(r"\bfolder\b|^my ", low)):  # "Photos" = the app
        return f
    m = re.fullmatch(r"(?:the |my )?([a-z])(?: drive|:| colon)(?: drive)?", re.sub(r"\s+folder$", "", low))
    if m:
        return m.group(1).upper() + ":/"
    if re.fullmatch(r"[a-z]:[\\/].*", low):
        return low
    return None


def _open(t: str, ctx: Ctx, flags) -> Optional[Action]:
    m = re.fullmatch(r"(?:open|launch|start|run|fire up|bring up|load|show me|pull up|go to|visit|navigate to|take me to)\s+(?:up\s+)?(.+)", t, I)
    if not m:
        if re.fullmatch(r"(?:the |your |a )?(?:own )?(?:web )?browser", t, I):
            return Action("browser_open", {"target": "https://www.google.com"})
        return None
    obj = re.sub(r"^(?:the|my|a|an|your)\s+", "", m.group(1).strip(), flags=I).strip()
    low = obj.lower()
    if re.fullmatch(r"(?:own |playwright |web )?browser", low) or (flags["browser"] and low in ("", "it")):
        return Action("browser_open", {"target": "https://www.google.com"})
    mr = re.fullmatch(r"(?P<n>first|1st|top|second|2nd|third|3rd|fourth|4th|fifth|5th)\s+(?:link|result|search result|one|website|site|hit)"
                      r"(?:\s+(?:in|on|over)\s+(?:the\s+)?(?:\w+\s+)?browser)?", low)
    if mr:  # "open the first link" – a search result, never a search for the words "first link"
        return Action("browser_click", {"result": ORDINAL[mr.group("n")]}) if (flags["browser"] or ctx.browser_open) else None
    folder = _folder(low)
    if folder:
        return Action("open_folder", {"folder": folder})
    if low.endswith(" folder"):
        return Action("find_files", {"query": obj[:-7], "open_first": True}, soft=True)
    site = _is_site(low)
    if site and not (_known_app(low) and not re.search(r"\b(?:website|site|\.com)\b", low)):
        if flags["browser"] or (ctx.browser_open and site not in ("youtube",)):
            return Action("browser_open", {"target": site})
        return Action("open_website", {"site": site})
    if flags["browser"]:
        return Action("browser_open", {"target": obj})
    if _is_app(low):
        return Action("open_app", {"name": re.sub(r"\s+(?:app|application)$", "", obj, flags=I)}, soft=True)
    return None  # not sure what it is → the AI decides (app? site? file?)


def _close(t: str, ctx: Ctx, flags) -> Optional[Action]:
    m = re.fullmatch(r"(?:close|quit|exit|kill|shut|terminate|end)\s+(?:down\s+)?(.+)", t, I)
    if not m:
        return None
    obj = re.sub(r"^(?:the|my|a|your|this)\s+", "", m.group(1).strip(), flags=I)
    low = obj.lower()
    if re.fullmatch(r"(?:own |playwright |web )?browser(?: window)?", low):
        return Action("browser_close", {})
    if re.fullmatch(r"(?:this |current |the )?tab", low):
        return Action("browser_tabs", {"action": "close"})
    if re.fullmatch(r"(?:the )?(?:timer|reminder|alarm)s?", low):
        return Action("cancel_timer", {"which": "all" if low.endswith("s") else "timer"})
    if low in ("zoha", "yourself", "assistant", "pc", "computer", "laptop", "system", "full screen", "fullscreen"):
        return None
    if len(obj.split()) > 4:
        return None
    name = re.sub(r"\s+(?:window|app|application)$", "", obj, flags=I)
    if _is_app(name.lower()):
        return Action("close_app", {"name": name}, soft=True)
    return None


def _search(t: str, ctx: Ctx, flags) -> Optional[Action]:
    m = re.fullmatch(r"(?:search|google|look up|lookup|search up|find)(?: for| about)?\s+(.+?)(?:\s+on (?:google|the web|the internet|internet))?", t, I)
    if not m:
        return None
    q = m.group(1).strip()
    if re.match(r"(?:my |the )?(?:file|files|document|folder|resume|cv|pdf)\b", q, I) or q.lower().startswith("my "):
        return None  # "find my resume" → LLM chooses find_files with the right query
    fq = re.fullmatch(r"(?:the |my )?(.+?)(?: and open it| and open)?", q, I).group(1)
    if t.lower().startswith("find") and re.search(r"\b(?:project|notes?|resume|cv|proposal|invoice|photo|marksheet|synopsis|presentation|"
                                                  r"ppt|pdf|docx?|report|assignment|code|file|folder|screenshot|certificate)\b", fq, I):
        return Action("find_files", {"query": fq, "open_first": bool(re.search(r"and open", q, I))})
    if flags["browser"] or ctx.browser_open:
        return Action("browser_open", {"target": q})
    return Action("web_search", {"query": q})


def _nav(t: str, ctx: Ctx, flags) -> Optional[Action]:
    if not ctx.browser_open:
        return None
    if re.fullmatch(r"(?:go )?back(?: to the (?:previous|last) page)?|previous page|go to the previous page", t, I):
        return Action("browser_nav", {"action": "back"})
    if re.fullmatch(r"(?:go )?forward(?: a page)?|next page", t, I):
        return Action("browser_nav", {"action": "forward"})
    if re.fullmatch(r"(?:refresh|reload)(?: the)?(?: page| tab)?", t, I):
        return Action("browser_nav", {"action": "reload"})
    m = re.fullmatch(r"scroll(?: the page)? (down|up|to the top|to the bottom|top|bottom)(?: a bit| more)?", t, I)
    if m:
        d = m.group(1).lower().replace("to the ", "")
        return Action("browser_scroll", {"direction": d})
    if re.fullmatch(r"(?:open )?(?:a )?new tab", t, I):
        return Action("browser_tabs", {"action": "new"})
    m = re.fullmatch(r"(?:switch|go) to (?:the )?(?:tab )?(\d+|first|second|third|last)(?: tab)?", t, I)
    if m:
        k = {"first": 1, "second": 2, "third": 3}.get(m.group(1).lower())
        return Action("browser_tabs", {"action": "switch", "index": k or (int(m.group(1)) if m.group(1).isdigit() else 1)})
    return None


def _timer(t: str) -> Optional[Action]:
    t = re.sub(r"\btimer of\b", "timer for", t, flags=I)
    m = re.fullmatch(r"(?:set|start|put|make)(?: up)?(?: an?| the)? (?:timer|countdown|alarm)(?: for)? " + NUM, t, I)
    if m and m.group(1).lower() not in ("a", "an"):
        v = _num(m.group(1))
        if v:
            return Action("set_timer", {"minutes": v, "label": ""})  # "set a timer of 5" → minutes
    m = re.fullmatch(r"(?:set|start|put|make)?(?: up)?(?: an?| the)?(?: (?:timer|alarm|countdown))?(?: for)? " + NUM +
                     r"[ -](seconds?|secs?|minutes?|mins?|hours?|hrs?)(?:[ -](?:timer|countdown|alarm))?(?: for (.+))?|"
                     r"(?:set|start|put)(?: an?| the)? (?:timer|countdown|alarm) for " + NUM + r" (seconds?|secs?|minutes?|mins?|hours?|hrs?)(?: for (.+))?|"
                     r"(?:timer|countdown) " + NUM + r" (seconds?|secs?|minutes?|mins?|hours?|hrs?)(?: for (.+))?", t, I)
    if m:
        g = [x for x in m.groups()]
        n, unit, label = next(((g[i], g[i + 1], g[i + 2]) for i in (0, 3, 6) if g[i]), (None, None, None))
        v = _num(n or "")
        if v is None:
            return None
        u = unit.lower()
        mins = v / 60 if u.startswith("s") else v * 60 if u.startswith("h") else v
        return Action("set_timer", {"minutes": round(mins, 3), "label": (label or "").strip()})
    if re.fullmatch(r"(?:cancel|stop|delete|remove|clear)(?: (?:the|my|all|all the))? (?:timers?|alarms?|reminders?|countdowns?)", t, I):
        return Action("cancel_timer", {"which": "all"})
    if re.fullmatch(r"(?:what|which|list|show)(?: are)?(?: my)? (?:timers?|reminders?)(?: (?:are )?(?:running|set|active))?|how (?:long|much time)(?: is)?(?: left)?(?: on)?(?: the| my)? timer", t, I):
        return Action("list_timers", {})
    return None


def _remind(t: str) -> Optional[Action]:
    RM = r"(?:remind me|(?:set|add|create|make|put|schedule)(?: up)?(?: an?| the| me an?)? reminder)"
    m = re.fullmatch(RM + r" (?:to |about |that |for |of )?(.+?) (?:at|by|for) " + CLOCK + r"(?: today| tonight| tomorrow)?", t, I) or \
        re.fullmatch(r"(?:at|by) " + CLOCK + r",? remind me (?:to |about )?(.+)", t, I) or \
        re.fullmatch(RM + r" (?:at|for|by) " + CLOCK + r" (?:to |about |that |for |of )(.+)", t, I)
    if m:
        a, b = [x for x in m.groups() if x is not None]
        msg, clock = (a, b) if not re.match(r"\d|noon|midnight", a, I) else (b, a)
        hhmm = _clock(clock)
        if hhmm:
            return Action("set_reminder", {"message": msg.strip(), "at_time": hhmm})
    m = re.fullmatch(RM + r" (?:to |about |that |for |of )?(.+?) in " + NUM + r" (minutes?|mins?|hours?|hrs?)", t, I) or \
        re.fullmatch(r"in " + NUM + r" (minutes?|mins?|hours?|hrs?),? remind me (?:to |about )?(.+)", t, I) or \
        re.fullmatch(RM + r" in " + NUM + r" (minutes?|mins?|hours?|hrs?) (?:to |about |that |for |of )(.+)", t, I)
    if m:
        g = [x for x in m.groups() if x is not None]
        msg, n, unit = (g[0], g[1], g[2]) if not re.fullmatch(NUM, g[0], I) else (g[2], g[0], g[1])
        v = _num(n)
        if v:
            return Action("set_reminder", {"message": msg.strip(), "in_minutes": v * (60 if unit.lower().startswith("h") else 1)})
    return None


def _misc(t: str) -> Optional[Action]:
    low = t.lower()
    if re.search(r"\b(?:you (?:didn'?t|did not|never|forgot to|haven'?t)|where(?:'s| is)|did you)\b.*\b(?:timers?|reminders?|alarms?|remind)\b", low) \
            or re.search(r"\b(?:timer|reminder|alarm) (?:didn'?t|did not|never) (?:go off|ring|work|come)", low):
        return Action("list_timers", {})
    if re.fullmatch(r"(?:take|capture|grab)(?: a| the)? (?:screen ?shot|screen capture|snapshot of (?:the|my) screen)|screen ?shot(?: (?:the|my) screen)?", low):
        return Action("take_screenshot", {})
    if re.fullmatch(r"lock(?: (?:my|the))? (?:pc|computer|laptop|screen|system|workstation)", low):
        return Action("lock_pc", {})
    if re.fullmatch(r"(?:what(?:'?s| is) the )?(?:time|current time)(?: now| right now)?|what time is it(?: now)?|tell me the time", low):
        return Action("get_datetime", {})
    if re.fullmatch(r"(?:what(?:'?s| is) (?:the |today'?s )?)(?:date|day)(?: today)?|what day is (?:it|today)|today'?s date", low):
        return Action("get_datetime", {})
    if re.fullmatch(r"(?:system status|system stats|pc status|how'?s my (?:pc|computer|laptop|system)(?: doing)?|check (?:my )?(?:cpu|ram|battery|system)(?: usage| status)?|"
                    r"(?:how much )?battery(?: level| left| percentage)?|cpu usage|ram usage|gpu usage)", low):
        return Action("system_status", {})
    m = re.fullmatch(r"(?:what(?:'?s| is) the |how(?:'?s| is) the |check the |show me the |tell me the )?weather(?: like)?(?: (?:in|at|for) ([a-z .'-]+?))?"
                     r"(?: (today|tomorrow|tonight))?|(?:will it|is it going to) rain(?: (today|tomorrow))?(?: in ([a-z .'-]+))?|"
                     r"(?:how hot|how cold|what'?s the temperature)(?: is it)?(?: (?:in|at) ([a-z .'-]+?))?(?: (today|tomorrow))?", low)
    if m:
        g = [x for x in m.groups() if x]
        day = next((x for x in g if x in ("today", "tomorrow", "tonight")), "today")
        city = next((x for x in g if x not in ("today", "tomorrow", "tonight")), None)
        args = {"day": "tomorrow" if day == "tomorrow" else "today"}
        if city:
            args["city"] = city.strip().title()
        return Action("get_weather", args)
    m = re.fullmatch(r"(?:take|make|write|jot)(?: down)?(?: a| this)? note(?: that| saying| of)?[:,]?\s+(.+)|note(?: down)?[:,]?\s+(.+)|add (.+) to my notes", t, I)
    if m:
        return Action("create_note", {"text": next(x for x in m.groups() if x).strip()})
    if re.fullmatch(r"(?:read|show|what are)(?: me)?(?: my)?(?: recent| last)? notes", low):
        return Action("read_notes", {})
    m = re.fullmatch(r"(?:don'?t|do not) forget (?:that )?(.+)", t, I)
    if m and len(m.group(1).split()) >= 3:
        return Action("remember", {"fact": m.group(1).strip()})
    m = re.fullmatch(r"(?:forget|delete|remove|erase|clear|wipe)(?: (?:the|my|that|your))?(?: (?:memory|memories|fact|facts|thing))?"
                     r" ?(?:about|of|regarding|on|related to|that|what i said about|everything about)\s+(.+)|forget (?:that |about )?(.+)", t, I)
    if m:
        about = (m.group(1) or m.group(2)).strip()
        about = re.sub(r"^(?:the|my)\s+", "", about)
        if about and about.lower() not in ("it", "that", "this", "nothing", "everything"):
            return Action("forget", {"about": about})
    m = re.fullmatch(r"remember (?:that )?(.+)", t, I)
    if m and len(m.group(1).split()) >= 3:
        return Action("remember", {"fact": m.group(1).strip()})
    m = re.fullmatch(r"(shut ?down|turn off|switch off|power off|power down|restart|reboot|sleep)(?: (?:the|my))? (?:pc|computer|laptop|system|machine)"
                     r"|(shut ?down|power off|reboot)|put (?:the |my )?(?:pc|computer|laptop|system) to (sleep)|make (?:the |my )?(?:pc|computer|laptop) (sleep)", low)
    if m:
        w = next(x for x in m.groups() if x)
        act = "restart" if w in ("restart", "reboot") else "sleep" if w == "sleep" else "shutdown"
        return Action("power", {"action": act})
    if re.fullmatch(r"cancel (?:the )?(?:shutdown|restart)", low):
        return Action("power", {"action": "cancel"})
    if re.fullmatch(r"(?:what(?:'?s| is) the )?(?:latest |today'?s |top )?(?:news|headlines)(?: today)?", low):
        return Action("news_headlines", {})
    return None


# ── public API ───────────────────────────────────────────────────────────────
VERBS = (r"play|pause|stop|resume|open|launch|start|close|quit|exit|kill|search|google|look up|set|turn|mute|unmute|"
         r"take|lock|skip|next|go|make|put|show|bring|fire|remind|note|cancel|maximi[sz]e|minimi[sz]e|scroll|"
         r"refresh|reload|rewind|forward|volume|what|check|find")
VERB_START = re.compile(r"^(?:" + VERBS + r")\b", I)


HI_CLOSE = r"(?:band|bandh|off)\s*(?:karo|kar do|kardo|kar de|karde|kar|kar dijiye)"
HI_OPEN = r"(?:kholo|khol do|kholdo|khol de|open karo|open kar do|start karo|chalu karo)"
HI_PLAY = r"(?:chalao|chala do|chalado|laga do|lagao|bajao|baja do|play karo|play kar do|sunao|suna do)"
HI_STOP = r"(?:rok do|roko|ruko|rok de|pause karo|pause kar do|thamba)"


def _hinglish(t: str, ctx: Ctx) -> Optional[Action]:
    low = t.lower().strip(" .!?")
    video_ctx = "youtube.com" in ctx.browser_url
    m = re.fullmatch(r"(?:" + NUM + r"|ek|do|teen|paanch|das|bees|pachees|tees)\s*(minutes?|mins?|seconds?|secs?|hours?|hrs?|ghante|ghanta)"
                     r"\s+ka\s+(?:timer|time)(?:\s+(?:lagao|laga do|lagado|set karo|set kar do|laga de|chalu karo))?", low)
    if m:
        word = (m.group(1) or re.match(r"\S+", low).group(0)).lower()
        n = {"ek": 1, "do": 2, "teen": 3, "paanch": 5, "das": 10, "bees": 20, "pachees": 25, "tees": 30}.get(word) or _num(word) or 1
        unit = m.group(2)
        mins = n / 60 if unit.startswith("sec") else n * 60 if unit.startswith(("hour", "hr", "ghant")) else n
        return Action("set_timer", {"minutes": round(float(mins), 4), "label": ""})
    m = re.fullmatch(r"(.+?)\s+" + HI_CLOSE, low)
    if m:
        obj = re.sub(r"^(?:the|ye|yeh|this)\s+", "", m.group(1)).strip()
        if obj in ("pc", "computer", "laptop", "system"):
            return Action("power", {"action": "shutdown"})
        if obj in ("gaana", "gana", "music", "song", "gaane", "audio"):
            return Action("media_control", {"action": "pause"})
        if obj in ("video", "youtube"):
            return Action("browser_video", {"action": "pause"}) if video_ctx else Action("media_control", {"action": "pause"})
        if re.fullmatch(r"(?:captions?|subtitles?|cc|subs)", obj):
            return Action("browser_video", {"action": "captions_off"}) if ctx.browser_open else None
        if obj in ("timer", "reminder", "alarm"):
            return Action("cancel_timer", {"which": "all"})
        if obj in ("browser",):
            return Action("browser_close", {})
        if _is_app(obj):
            return Action("close_app", {"name": obj}, soft=True)
        return None
    m = re.fullmatch(r"(.+?)\s+" + HI_STOP, low)
    if m and re.sub(r"^(?:the|ye|yeh)\s+", "", m.group(1)) in ("video", "gaana", "gana", "music", "song", "youtube", "it", "ise", "isko"):
        return Action("browser_video", {"action": "pause"}) if video_ctx and "gaana" not in m.group(1) else Action("media_control", {"action": "pause"})
    m = re.fullmatch(r"(.+?)\s+" + HI_OPEN, low)
    if m:
        return _open("open " + m.group(1), ctx, {"browser": False, "youtube": False, "spotify": False})
    m = re.fullmatch(r"(?:(youtube|spotify)\s+(?:pe|par|mein|me)\s+)?(.+?)\s+" + HI_PLAY, low)
    if m and not re.search(r"\b(?:timer|alarm|reminder)\b", m.group(2)):
        what = m.group(2).strip()
        if what in ("video", "gaana", "gana", "music", "song", "it", "ise", "isko"):
            return Action("browser_video", {"action": "play"}) if video_ctx and what == "video" else Action("media_control", {"action": "play"})
        if m.group(1) == "spotify":
            return Action("play_spotify", {"query": what})
        return Action("play_youtube", {"query": what, "where": "default"})
    if re.fullmatch(r"(?:agla|next) (?:gaana|gana|song|video)(?: (?:chalao|lagao|bajao|play karo))?", low):
        return Action("media_control", {"action": "next"})
    if re.fullmatch(r"(?:pichla|pichhla|previous) (?:gaana|gana|song)(?: (?:chalao|lagao|bajao))?", low):
        return Action("media_control", {"action": "previous"})
    if re.fullmatch(r"(?:awaaz|awaz|volume|sound)\s+(?:badhao|badha do|zyada karo|tez karo|increase karo|upar karo)", low):
        return Action("set_volume", {"change": "up"})
    if re.fullmatch(r"(?:awaaz|awaz|volume|sound)\s+(?:kam karo|kam kar do|ghatao|dheere karo|decrease karo|neeche karo)", low):
        return Action("set_volume", {"change": "down"})
    m = re.fullmatch(r"(?:awaaz|awaz|volume)\s+(\d{1,3})\s*(?:percent|%)?\s*(?:karo|kar do|pe rakho|set karo)?", low)
    if m:
        return Action("set_volume", {"level": int(m.group(1))})
    if re.fullmatch(r"screen ?shot (?:le lo|lo|lelo|le|nikalo)", low):
        return Action("take_screenshot", {})
    if re.fullmatch(r"(?:time|samay) (?:kya hua hai|kya hai|kitna hua|batao)|kitne baje(?: hai)?", low):
        return Action("get_datetime", {})
    m = re.fullmatch(r"(?:aaj )?([a-z ]+?) (?:ka|ki) (?:mausam|weather)(?: kaisa hai| batao| kya hai)?", low)
    if m:
        return Action("get_weather", {"city": m.group(1).strip().title(), "day": "today"})
    m = re.fullmatch(r"(?:note karo|note kar lo|likh lo)[:,]?\s+(.+)", t, I)
    if m:
        return Action("create_note", {"text": m.group(1).strip()})
    m = re.fullmatch(r"(?:yaad rakhna|yaad rakho)[:,]?\s+(?:ki\s+)?(.+)", t, I)
    if m:
        return Action("remember", {"fact": m.group(1).strip()})
    return None


def _platform_play(core: str, flags) -> Optional[Action]:
    """'start O Maahi on YouTube', 'put Kesariya on Spotify', 'search YouTube for Rap God and play it'."""
    m = re.fullmatch(r"(?:search|look up|find)\s+(?:on\s+)?(youtube|spotify)\s+for\s+(.+?)(?:\s+and\s+play(?: it| that)?)?", core, I)
    if m:
        q = m.group(2).strip()
        return Action("play_spotify", {"query": q}) if m.group(1).lower() == "spotify" else Action("play_youtube", {"query": q, "where": "default"})
    if not (flags["youtube"] or flags["spotify"]):
        return None
    m = re.fullmatch(r"(?:start|put on|put|open|search(?: for)?|find|queue|blast|stream)\s+(.+)", core, I)
    if not m:
        return None  # "play X on YouTube" → _play (cleans the query, knows about the browser)
    from .tools import clean_media_query

    q = clean_media_query(m.group(1).strip())
    if q.lower() in MEDIA_WORDS or q.lower() in ("youtube", "spotify", "music", "something"):
        return None
    return Action("play_spotify", {"query": q}) if flags["spotify"] else \
        Action("play_youtube", {"query": q, "where": "browser" if flags["browser"] else "default"})


def _single(t: str, ctx: Ctx) -> Optional[Action]:
    flags = {"browser": bool(BROWSER_MOD.search(" " + t)), "youtube": bool(YOUTUBE_MOD.search(" " + t)),
             "spotify": bool(SPOTIFY_MOD.search(" " + t))}
    core = t
    for rx in (BROWSER_MOD, YOUTUBE_MOD, SPOTIFY_MOD, LAPTOP_MOD):
        core = rx.sub(" ", " " + core).strip()
    core = re.sub(r"\s+", " ", normalise(core)).strip(" ,.")
    if not core:
        return None
    a = _hinglish(normalise(t), ctx) or _platform_play(core, flags) or _platform_play(normalise(t), flags)
    if a:
        return a
    for fn in (_media, _video, _volume, _timer, _remind, _misc, _nav, _calendar, _play, _close, _search, _open):
        a = fn(core, ctx, flags) if fn in (_media, _video, _play, _open, _close, _search, _nav, _calendar) else fn(core)
        if a:
            return a
    # "<anything> browser" leftovers: "start the browser" with modifiers stripped
    if flags["browser"] and re.fullmatch(r"(?:open|start|launch)", core, I):
        return Action("browser_open", {"target": "https://www.google.com"})
    return None


ORDINAL = {"first": 1, "1st": 1, "top": 1, "one": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "fifth": 5, "5th": 5}
_RESULT = r"(?:open|click|click on|go to|visit|take me to)\s+(?:the\s+)?(?P<n>first|1st|top|second|2nd|third|3rd|fourth|4th|fifth|5th)\s+(?:link|result|search result|one|website|site|page|hit)"
SEARCH_THEN_OPEN = re.compile(
    r"(?:(?:open|start|launch)\s+(?:the\s+|your\s+|a\s+)?(?:own\s+|playwright\s+|new\s+)*browser\s*,?\s*(?:and\s+(?:then\s+)?)?)?"
    r"(?:search|google|look up|find)\s+(?:for\s+)?(?P<q>.+?)\s*,?\s+(?:and\s+then|and|then)\s+" + _RESULT + r"(?:\s+(?:for me|please))?", I)
OPEN_RESULT = re.compile(_RESULT + r"(?:\s+(?:for me|please))?", I)


def _search_then_open(t: str, ctx: Ctx) -> Optional[List[Action]]:
    """'search X (over the browser) and open the first link' → search, then open result 1 – one reliable step."""
    m = SEARCH_THEN_OPEN.fullmatch(t)
    if m:
        q = BROWSER_MOD.sub("", " " + m.group("q")).strip(" ,")
        q = re.sub(r"\s+(?:on|over|in)\s+(?:google|the web|internet)$", "", q, flags=I).strip()
        if q:
            return [Action("browser_open", {"target": q, "open_result": ORDINAL[m.group("n").lower()]})]
    m = OPEN_RESULT.fullmatch(t)
    if m and ctx.browser_open:
        return [Action("browser_click", {"result": ORDINAL[m.group("n").lower()]})]
    return None


def parse(text: str, ctx: Optional[Ctx] = None) -> List[Action]:
    ctx = ctx or Ctx()
    t = normalise(text)
    if not t:
        return []
    so = _search_then_open(t, ctx)
    if so:
        return so
    whole = _platform_play(t, {"browser": False, "youtube": False, "spotify": False})
    if whole:
        return [whole]
    m = re.fullmatch(r"(?:find|search for|look for|locate)\s+(?:the |my )?(.+?)\s+and\s+open(?: it| that)?", t, I)
    if m:
        return [Action("find_files", {"query": m.group(1).strip(), "open_first": True})]
    # "start the browser and play X" → the play inherits "browser"
    browser_everywhere = bool(re.search(r"\bbrowser\b", t, I))
    parts = [p.strip(" ,") for p in re.split(r",?\s+(?:and then|and also|and|then|after that)\s+(?=(?:also |please )?(?:" + VERBS + r")\b)|;\s*|,\s+(?=(?:" + VERBS + r")\b)", t, flags=I) if p.strip(" ,")]
    if len(parts) > 1 and all(VERB_START.match(normalise(p)) for p in parts):
        acts = []
        for p in parts:
            p2 = p + (" in the browser" if browser_everywhere and not BROWSER_MOD.search(" " + p) and re.match(r"(?:play|search|open|go)", normalise(p), I) else "")
            a = _single(p2, ctx)
            if not a:
                return []  # one part not understood → let the LLM do the whole thing
            acts.append(a)
        # "open the browser and play X" → the second action already opens the browser
        # "open the browser / open YouTube … and play X" → playing already opens it
        if len(acts) == 2 and acts[0].tool == "open_app" and str(acts[0].args.get("name", "")).lower() == "spotify" \
                and acts[1].tool == "play_youtube":
            return [Action("play_spotify", {"query": acts[1].args["query"]})]
        if len(acts) == 2 and acts[0].tool in ("browser_open", "open_website", "open_app") and acts[1].tool in ("browser_open", "play_youtube"):
            first = str(acts[0].args.get("target") or acts[0].args.get("site") or acts[0].args.get("name") or "").lower()
            if first in ("https://www.google.com", "") or "youtube" in first or (acts[1].tool == "browser_open" and "browser" in first):
                acts = acts[1:]
        return acts
    a = _single(t, ctx)
    return [a] if a else []
