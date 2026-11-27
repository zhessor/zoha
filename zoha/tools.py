"""
Desktop tools Zoha can call (LLM function calling).

Each tool = JSON-schema + Python function returning a short result string that the
model turns into a natural reply. Windows-first, with Linux/macOS fallbacks where
cheap. Nothing here runs arbitrary shell commands.
"""

from __future__ import annotations

import ctypes
import datetime as dt
import difflib
import json
import logging
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("zoha.tools")
WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if WIN else 0
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]
    fn: Callable[..., str]
    label: str  # short human label for the GUI action card
    icon: str


REGISTRY: Dict[str, Tool] = {}


def tool(_name: str, _description: str, _label: str, _icon: str = "⚡", **props):
    """props: name=(type, description, required:bool[, enum])"""
    properties, required = {}, []
    for pname, spec in props.items():
        ptype, pdesc, req = spec[0], spec[1], spec[2]
        p = {"type": ptype, "description": pdesc}
        if len(spec) > 3 and spec[3]:
            p["enum"] = spec[3]
        properties[pname] = p
        if req:
            required.append(pname)
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required

    def deco(fn):
        REGISTRY[_name] = Tool(_name, _description, schema, fn, _label, _icon)
        return fn

    return deco


class ToolContext:
    """Injected by the engine so tools can reach memory, timers and notifications."""

    vision = None  # callable(prompt, jpeg_bytes) -> str, when the active brain can see images
    last_user_text = ""
    turn_started = 0.0
    memory = None
    settings = None
    schedule: Callable[[float, str, str], str] = lambda delay, label, kind: "Timers unavailable."
    list_timers: Callable[[], str] = lambda: "No timers."
    browser_open_hint: Optional[bool] = None  # tests: pretend Zoha's browser is open/closed
    cancel_timer: Callable[[str], str] = lambda q: "No timers."
    writer = None  # callable(prompt) -> str: plain text from the active brain (no tools), for write_file
    last_file = None   # the page/file Zoha wrote or improved most recently ("improve it", "open it")
    last_listing = []  # numbered results of the last find_files ("open number 3")


CTX = ToolContext()


def call_tool(name: str, args: Dict[str, Any]) -> str:
    t = REGISTRY.get(name)
    if not t:
        return f"Error: unknown tool {name}"
    try:
        clean = {k: v for k, v in (args or {}).items() if k in t.parameters.get("properties", {})}
        res = t.fn(**clean)
        return str(res) if res is not None else "Done."
    except TypeError as e:
        return f"Error: bad arguments for {name}: {e}"
    except Exception as e:
        if type(e).__name__ in ("BrowserError", "TimeoutError", "Error") or "Playwright isn't installed" in str(e):
            msg = str(e).splitlines()[0][:300]
            return f"Error: {msg}"
        log.exception("Tool %s failed", name)
        return f"Error while running {name}: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────
def _http_get(url: str, timeout: float = 8.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _ps(script: str, timeout: float = 15, env: Optional[dict] = None) -> str:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW,
        env={**os.environ, **(env or {})},
    )
    return (r.stdout or "").strip()


def _open(target: str):
    if WIN:
        os.startfile(target)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def _fuzzy_best(query: str, names: List[str], cutoff: float = 0.6) -> Optional[str]:
    q = query.lower().strip()
    if not names:
        return None
    lower = {n.lower(): n for n in names}
    if q in lower:
        return lower[q]
    # word-boundary containment ("vs code" ⊂ "visual studio code" handled by aliases)
    starts = [n for n in names if n.lower().startswith(q)]
    if starts:
        return min(starts, key=len)
    contains = [n for n in names if re.search(rf"\b{re.escape(q)}\b", n.lower())]
    if contains:
        return min(contains, key=len)
    m = difflib.get_close_matches(q, list(lower.keys()), n=1, cutoff=cutoff)
    return lower[m[0]] if m else None


# ──────────────────────────────────────────────────────────────────────────────
# App index (Start Menu: classic + Store apps)
# ──────────────────────────────────────────────────────────────────────────────
APP_ALIASES = {
    "vs code": "visual studio code", "vscode": "visual studio code", "code": "visual studio code",
    "chrome": "google chrome", "edge": "microsoft edge", "word": "word", "excel": "excel",
    "powerpoint": "powerpoint", "terminal": "terminal", "cmd": "command prompt", "command prompt": "command prompt",
    "calculator": "calculator", "calc": "calculator", "settings": "settings", "file explorer": "file explorer",
    "explorer": "file explorer", "files": "file explorer", "task manager": "task manager", "paint": "paint",
    "camera": "camera", "photos": "photos", "store": "microsoft store", "whatsapp": "whatsapp",
    "telegram": "telegram", "discord": "discord", "spotify": "spotify", "steam": "steam", "obs": "obs studio",
    "notepad": "notepad", "windsurf": "windsurf", "figma": "figma", "postman": "postman", "teams": "microsoft teams",
    "outlook": "outlook", "snipping tool": "snipping tool", "clock": "clock", "control panel": "control panel",
}
FALLBACK_EXE = {
    "notepad": "notepad.exe", "calculator": "calc.exe", "command prompt": "cmd.exe", "paint": "mspaint.exe",
    "task manager": "taskmgr.exe", "file explorer": "explorer.exe", "control panel": "control.exe",
    "settings": "ms-settings:", "spotify": "spotify:", "microsoft store": "ms-windows-store:",
    "camera": "microsoft.windows.camera:", "clock": "ms-clock:", "terminal": "wt.exe",
    "powershell": "powershell.exe", "snipping tool": "ms-screenclip:",
}
SITES = {
    "youtube": "https://youtube.com", "github": "https://github.com", "gmail": "https://mail.google.com",
    "google": "https://google.com", "reddit": "https://reddit.com", "linkedin": "https://linkedin.com",
    "instagram": "https://instagram.com", "twitter": "https://x.com", "x": "https://x.com",
    "netflix": "https://netflix.com", "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
    "vercel": "https://vercel.com/dashboard", "amazon": "https://amazon.in",
    "flipkart": "https://flipkart.com", "maps": "https://maps.google.com", "google maps": "https://maps.google.com",
    "drive": "https://drive.google.com", "google drive": "https://drive.google.com", "calendar": "https://calendar.google.com",
    "whatsapp web": "https://web.whatsapp.com", "notion": "https://notion.so", "canva": "https://canva.com",
    "figma web": "https://figma.com", "spotify web": "https://open.spotify.com", "leetcode": "https://leetcode.com",
    "stack overflow": "https://stackoverflow.com", "google calendar": "https://calendar.google.com",
    "google meet": "https://meet.google.com", "google docs": "https://docs.google.com", "google sheets": "https://sheets.google.com", "wikipedia": "https://wikipedia.org",
    "hotstar": "https://hotstar.com", "jiohotstar": "https://hotstar.com",
    "prime video": "https://primevideo.com", "swiggy": "https://swiggy.com", "zomato": "https://zomato.com",
    "codeforces": "https://codeforces.com", "geeksforgeeks": "https://geeksforgeeks.org", "gfg": "https://geeksforgeeks.org",
    "cricbuzz": "https://cricbuzz.com", "times of india": "https://timesofindia.indiatimes.com", "stackoverflow": "https://stackoverflow.com",
    "facebook": "https://facebook.com", "outlook web": "https://outlook.live.com", "perplexity": "https://perplexity.ai",
    "gemini": "https://gemini.google.com", "hacker news": "https://news.ycombinator.com", "irctc": "https://irctc.co.in",
    "myntra": "https://myntra.com", "kaggle": "https://kaggle.com", "hugging face": "https://huggingface.co", "x.com": "https://x.com",
}


class AppIndex:
    def __init__(self):
        self.apps: Dict[str, str] = {}  # name -> AppID
        self._ready = threading.Event()
        threading.Thread(target=self._build, daemon=True, name="zoha-appindex").start()

    def _build(self):
        try:
            if WIN:
                out = _ps("Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress", timeout=30)
                data = json.loads(out) if out else []
                if isinstance(data, dict):
                    data = [data]
                for a in data:
                    n, aid = a.get("Name"), a.get("AppID")
                    if n and aid and "uninstall" not in n.lower():
                        self.apps.setdefault(n, aid)
                log.info("App index: %d Start Menu apps", len(self.apps))
        except Exception as e:
            log.warning("App index failed: %s", e)
        finally:
            self._ready.set()

    def find(self, name: str) -> Optional[tuple]:
        self._ready.wait(8)
        q = APP_ALIASES.get(name.lower().strip(), name.lower().strip())
        best = _fuzzy_best(q, list(self.apps.keys()), cutoff=0.72)
        return (best, self.apps[best]) if best else None

    def names(self) -> List[str]:
        return sorted(self.apps.keys())


APPS = AppIndex()


# ──────────────────────────────────────────────────────────────────────────────
# What's on screen (for awareness + verifying actions)
# ──────────────────────────────────────────────────────────────────────────────
def visible_windows() -> List[tuple]:
    """[(title, process_name)] of visible top-level windows, front-most first (Windows only)."""
    if not WIN:
        return []
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    out: List[tuple] = []
    procs: Dict[int, str] = {}
    try:
        import psutil

        procs = {p.pid: (p.info["name"] or "") for p in psutil.process_iter(["name"])}
    except Exception:
        pass

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # skip owned/tool windows
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.strip()
        if title in ("Program Manager", "Settings", "Microsoft Text Input Application", "Windows Input Experience") or not title:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out.append((title, procs.get(pid.value, "")))
        return True

    try:
        user32.EnumWindows(cb, 0)
    except Exception:
        return []
    return out


def _window_matching(words: List[str]) -> Optional[str]:
    for title, proc in visible_windows():
        low = (title + " " + proc).lower()
        if any(w in low for w in words if len(w) >= 3):
            return title
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Apps & web
# ──────────────────────────────────────────────────────────────────────────────
@tool("open_app", "Open/launch an installed desktop application by name (e.g. Spotify, VS Code, WhatsApp, Calculator, Chrome). "
      "Websites (Netflix, LinkedIn, Leetcode, ChatGPT…) are NOT apps – use open_website.",
      "Open app", "🚀", name=("string", "Application name as the user said it", True))
def open_app(name: str) -> str:
    q = name.strip().lower()
    hit = APPS.find(q)
    if hit and WIN:
        display, aid = hit
        words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", display)] + [q]
        already = _window_matching(words)
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{aid}"], creationflags=NO_WINDOW)
        # verify: wait for its window to appear (up to ~6 s)
        for _ in range(24):
            time.sleep(0.25)
            w = _window_matching(words)
            if w and (w != already or already is None):
                return f"Opened {display}."
        if already:
            return f"{display} was already open – brought it up."
        return f"Started {display}; its window hasn't appeared yet (it may still be loading)."
    key = APP_ALIASES.get(q, q)
    if key in FALLBACK_EXE and WIN:
        target = FALLBACK_EXE[key]
        try:
            os.startfile(target)  # noqa
        except OSError:
            subprocess.Popen(["cmd", "/c", "start", "", target], creationflags=NO_WINDOW)
        return f"Opened {key.title()}."
    if not WIN:
        exe = shutil.which(q.replace(" ", "-")) or shutil.which(q.replace(" ", ""))
        if exe:
            subprocess.Popen([exe])
            return f"Opened {name}."
    if q in SITES:
        webbrowser.open(SITES[q])
        return f"{name} isn't installed as an app, so I opened the website."
    sugg = difflib.get_close_matches(q, [n.lower() for n in APPS.names()], n=3, cutoff=0.4)
    return f"Error: no installed app matches '{name}'." + (f" Closest: {', '.join(sugg)}." if sugg else "")


PROTECTED = {"explorer.exe", "system", "csrss.exe", "winlogon.exe", "svchost.exe", "lsass.exe", "dwm.exe",
             "services.exe", "smss.exe", "wininit.exe", "python.exe", "pythonw.exe", "py.exe"}


@tool("close_app", "Close (quit) a running application by name. 'Band karo' / 'shut' / 'kill' + an app name means close it – "
      "not pause music.", "Close app", "✖",
      name=("string", "Application name, e.g. 'chrome', 'spotify', 'notepad'", True))
def close_app(name: str) -> str:
    import psutil

    q = APP_ALIASES.get(name.lower().strip(), name.lower().strip())
    qk = re.sub(r"[^a-z0-9]", "", q)
    exe_hint = {"google chrome": "chrome", "microsoft edge": "msedge", "visual studio code": "code",
                "file explorer": "__never__", "command prompt": "cmd", "microsoft teams": "ms-teams",
                "obs studio": "obs64"}.get(q, qk)
    killed = set()
    for p in psutil.process_iter(["name", "pid"]):
        pn = (p.info["name"] or "").lower()
        if pn in PROTECTED or p.pid == os.getpid():
            continue
        base = re.sub(r"\.exe$", "", pn)
        if base == exe_hint or (len(exe_hint) >= 4 and base.startswith(exe_hint)):
            try:
                p.terminate()
                killed.add(p)
            except Exception:
                pass
    if killed:
        gone, alive = psutil.wait_procs(list(killed), timeout=3)
        for p in alive:  # verify: force-close anything that ignored the polite request
            try:
                p.kill()
            except Exception:
                pass
        names = sorted({(p.info.get("name") if hasattr(p, "info") else "") or "app" for p in killed})
        still = [p for p in alive if p.is_running()]
        if still:
            return f"Error: {', '.join(names)} didn't close."
        return f"Closed {', '.join(n.removesuffix('.exe') for n in names)}."
    return f"Error: {name} doesn't seem to be running."


@tool("open_website", "Open a website or URL in the default browser. Use for named sites (YouTube, GitHub, Gmail, Zhessor) or any domain.",
      "Open website", "🌐", site=("string", "Site name or URL/domain", True))
def open_website(site: str) -> str:
    s = site.strip()
    key = s.lower().removesuffix(".com") if s.lower() not in SITES else s.lower()
    if s.lower() in SITES or key in SITES:
        url = SITES.get(s.lower()) or SITES[key]
    elif re.match(r"^https?://", s):
        url = s
    elif "." in s and " " not in s:
        url = "https://" + s
    else:
        url = "https://www.google.com/search?btnI=1&q=" + urllib.parse.quote_plus(s)
    webbrowser.open(url)
    return f"Opened {url}."


@tool("web_search", "Open a Google search in the browser for the user to look at.", "Google search", "🔎",
      query=("string", "Search query", True))
def web_search(query: str) -> str:
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
    return f"Opened Google results for '{query}'."


def _strip_html(s: str) -> str:
    import html as _h

    return re.sub(r"\s+", " ", _h.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def _ddg(query: str) -> List[str]:
    html = _http_get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query))
    titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.S)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
    return [f"{_strip_html(t)} — {_strip_html(s)}" for t, s in zip(titles, snippets) if _strip_html(s)][:6]


def _wiki(query: str) -> List[str]:
    data = json.loads(_http_get("https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=3&srsearch="
                                + urllib.parse.quote(query)))
    return [f"Wikipedia: {r['title']} — {_strip_html(r['snippet'])}" for r in data.get("query", {}).get("search", [])]


def _gnews(query: str, n: int = 6) -> List[str]:
    xml = _http_get("https://news.google.com/rss/search?hl=en-IN&gl=IN&ceid=IN:en&q=" + urllib.parse.quote_plus(query))
    items = re.findall(r"<item>(.*?)</item>", xml, re.S)[:n]
    out = []
    for it in items:
        title = _strip_html(re.search(r"<title>(.*?)</title>", it, re.S).group(1)) if "<title>" in it else ""
        date = re.search(r"<pubDate>(.*?)</pubDate>", it)
        out.append(f"{title} ({date.group(1)[:16] if date else ''})")
    return out


@tool("web_lookup", "Look up live/current information on the web (facts after your knowledge cutoff, 'who is', prices, scores, 'latest'). Returns result snippets for YOU to read and summarise in your own words.",
      "Web lookup", "🛰", query=("string", "What to look up", True))
def web_lookup(query: str) -> str:
    rows: List[str] = []
    for fn in (_ddg, _wiki, _gnews):
        try:
            rows += fn(query)
        except Exception as e:
            log.debug("lookup source failed: %s", e)
        if len(rows) >= 5:
            break
    if not rows:
        return "Error: no web results (offline?)."
    return f"Results for '{query}' (today is {dt.date.today():%d %b %Y}):\n" + "\n".join(f"{i+1}. {r}" for i, r in enumerate(rows[:8]))


@tool("news_headlines", "Get the latest news headlines, optionally about a topic (default: India top news).", "News", "📰",
      topic=("string", "Topic, e.g. 'AI', 'Mumbai', 'cricket' (optional)", False))
def news_headlines(topic: str = "") -> str:
    try:
        rows = _gnews(topic or "India", 7)
    except Exception as e:
        return f"Error: news unavailable ({e})."
    return "Headlines:\n" + "\n".join(f"- {r}" for r in rows) if rows else "No headlines found."


@tool("play_youtube", "Play a song or video on YouTube — opens the top matching video directly so it starts playing. "
      "ALWAYS use this to play any song/video – never search YouTube and click results yourself. where='browser' plays it "
      "in YOUR browser (automatic if your browser is already open).",
      "Play on YouTube", "▶", query=("string", "Song / video to play", True),
      where=("string", "default = user's normal browser, browser = your own browser", False, ["default", "browser"]))
def play_youtube(query: str, where: str = "default") -> str:
    query = clean_media_query(query)
    try:
        html = _http_get("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query))
        ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
        if ids:
            url = f"https://www.youtube.com/watch?v={ids[0]}"
            if where != "browser" and where != "default_forced":
                try:
                    from .browser import _BROWSER

                    if _BROWSER is not None and _BROWSER.is_open():
                        where = "browser"  # her browser is already open → play there so she can control it
                except Exception:
                    pass
            if where == "browser":
                _br().open(url)
                return f"Playing '{query}' on YouTube in my browser."
            webbrowser.open(url)
            return f"Playing '{query}' on YouTube."
    except Exception as e:
        log.warning("YouTube lookup failed: %s", e)
    webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query))
    return f"Opened YouTube results for '{query}'."


@tool("play_spotify", "Open a search in the Spotify desktop app (use play_youtube when the user just says play a song).", "Spotify", "🎧",
      query=("string", "Song, artist or playlist", True))
def play_spotify(query: str) -> str:
    _open("spotify:search:" + urllib.parse.quote(query))
    return f"Opened Spotify search for '{query}'. The user picks the result (Spotify doesn't allow auto-play without its API)."


# ──────────────────────────────────────────────────────────────────────────────
# Media & volume (virtual key presses → works with any player)
# ──────────────────────────────────────────────────────────────────────────────
def clean_media_query(q: str) -> str:
    """'a song named until we met last time over the YouTube' → 'until we met last time'."""
    q = q.strip().strip(".!?\"'")
    q = re.sub(r"^(?:the |a |some )?(?:song|track|video|music|tune)s?\s+(?:named|called|titled)?\s*", "", q, flags=re.I)
    q = re.sub(r"^(?:named|called|titled)\s+", "", q, flags=re.I)
    q = re.sub(r"^(?:some|a few|a bit of)\s+(?=\w)", "", q, flags=re.I)
    q = re.sub(r"\s+(?:over|on|in|from|at)\s+(?:the\s+)?you\s?tube\b.*$", "", q, flags=re.I)
    q = re.sub(r"\s+(?:for me|please|now)$", "", q, flags=re.I)
    return q.strip().strip("\"'") or "music"


def _send_vk(vk: int, times: int = 1):
    if not WIN:
        return
    user32 = ctypes.windll.user32
    for _ in range(times):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.01)


# Windows media sessions (the same thing the volume flyout / media keys control): real play/pause, plus "what's playing"
_MEDIA_PS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTaskGeneric.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime] | Out-Null
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$sessions = @($mgr.GetSessions())
if ($sessions.Count -eq 0) { '{"ok":false,"none":true}'; exit }
$s = $mgr.GetCurrentSession()
# prefer a session that is actually playing (for pause/stop) or paused (for play)
$want = $env:ZOHA_MEDIA_ACTION
foreach ($c in $sessions) {
  $st = $c.GetPlaybackInfo().PlaybackStatus.ToString()
  if (($want -in @('pause','stop','status')) -and $st -eq 'Playing') { $s = $c; break }
  if (($want -eq 'play') -and $st -eq 'Paused') { $s = $c; break }
}
if ($null -eq $s) { $s = $sessions[0] }
$before = $s.GetPlaybackInfo().PlaybackStatus.ToString()
$ok = $true
switch ($want) {
  'pause'    { if ($before -eq 'Playing') { $ok = Await ($s.TryPauseAsync()) ([bool]) } }
  'play'     { if ($before -ne 'Playing') { $ok = Await ($s.TryPlayAsync()) ([bool]) } }
  'stop'     { if ($before -eq 'Playing') { $ok = Await ($s.TryPauseAsync()) ([bool]) } }
  'toggle'   { $ok = Await ($s.TryTogglePlayPauseAsync()) ([bool]) }
  'next'     { $ok = Await ($s.TrySkipNextAsync()) ([bool]) }
  'previous' { $ok = Await ($s.TrySkipPreviousAsync()) ([bool]) }
}
Start-Sleep -Milliseconds 350
$p = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
@{ ok = $ok; before = $before; after = $s.GetPlaybackInfo().PlaybackStatus.ToString(); title = $p.Title; artist = $p.Artist; app = $s.SourceAppUserModelId } | ConvertTo-Json -Compress
"""


def _media_session(action: str) -> Optional[dict]:
    if not WIN:
        return None
    try:
        out = _ps(_MEDIA_PS, timeout=12, env={"ZOHA_MEDIA_ACTION": action})
        line = next((l for l in out.splitlines() if l.strip().startswith("{")), "")
        return json.loads(line) if line else None
    except Exception as e:
        log.debug("media session failed: %s", e)
        return None


def _app_name(aumid: str) -> str:
    a = (aumid or "").lower()
    for key, name in (("chrome", "Chrome"), ("msedge", "Edge"), ("edge", "Edge"), ("spotify", "Spotify"), ("firefox", "Firefox"),
                      ("brave", "Brave"), ("vlc", "VLC"), ("zunemusic", "Media Player"), ("music", "Media Player")):
        if key in a:
            return name
    return aumid or "the player"


@tool("media_control", "Control music/video playing ANYWHERE on the PC (YouTube in any browser, Spotify, VLC…): pause, play/resume, "
      "stop, next, previous — or 'status' to find out what's playing. ALWAYS use this for any play/pause/stop/skip/resume request "
      "about current media; never just say it's done.", "Media", "⏯",
      action=("string", "What to do", True, ["pause", "play", "stop", "next", "previous", "toggle", "status"]))
def media_control(action: str) -> str:
    action = {"play_pause": "toggle", "resume": "play", "unpause": "play"}.get(action, action)
    info = _media_session(action)
    if info is None:
        # no WinRT access → fall back to media keys (toggle-based)
        if action == "status":
            return "Error: can't read what's playing on this system."
        vk = {"pause": 0xB3, "play": 0xB3, "toggle": 0xB3, "stop": 0xB2, "next": 0xB0, "previous": 0xB1}.get(action)
        if vk is None:
            return "Error: unknown media action."
        _send_vk(vk)
        return {"next": "Skipped to the next track.", "previous": "Went back a track.", "stop": "Sent stop."}.get(action, "Toggled play/pause.")
    if info.get("none"):
        return "Nothing is playing — no media is open on the PC right now."
    what = info.get("title") or "the media"
    if info.get("artist"):
        what += f" by {info['artist']}"
    where = _app_name(info.get("app", ""))
    before, after = info.get("before"), info.get("after")
    if action == "status":
        return f"{what} in {where} is {(after or before or 'unknown').lower()}."
    if not info.get("ok"):
        return f"Error: {where} didn't accept the {action} command."
    if action in ("pause", "stop"):
        return f"Paused {what} in {where}." if before == "Playing" else f"{what} was already paused."
    if action == "play":
        return f"Playing {what} in {where}." if before != "Playing" else f"{what} is already playing."
    if action == "next":
        return f"Skipped. Now: {what}."
    if action == "previous":
        return f"Went back. Now: {what}."
    return f"{what} is now {(after or '').lower()}."


@tool("set_volume", "Change system volume: set an exact level, or step up/down, or mute/unmute.", "Volume", "🔊",
      level=("integer", "Exact volume 0-100 (optional)", False),
      change=("string", "Relative change (optional)", False, ["up", "down", "mute", "unmute"]))
def set_volume(level: Optional[int] = None, change: Optional[str] = None) -> str:
    if level is not None and not str(level).replace(".", "", 1).isdigit():
        level = None
    if not WIN:
        return "Error: volume control is Windows-only for now."
    if level is not None:
        asked = int(float(level))
        level = max(0, min(100, asked))
        _send_vk(0xAE, 50)  # to 0 (each step = 2 %)
        _send_vk(0xAF, round(level / 2))
        if asked > 100:
            return f"Volume only goes up to 100 percent, so I set it to the maximum, 100."
        return f"Volume set to {level} percent."
    if change in ("mute", "unmute"):
        _send_vk(0xAD)
        return "Toggled mute."
    if change == "down":
        _send_vk(0xAE, 5)
        return "Volume down."
    _send_vk(0xAF, 5)
    return "Volume up."


# ──────────────────────────────────────────────────────────────────────────────
# System
# ──────────────────────────────────────────────────────────────────────────────
@tool("system_status", "Get live CPU, RAM, disk, battery, GPU and uptime stats of this PC.", "System status", "📊")
def system_status() -> str:
    import psutil

    parts = [f"CPU {psutil.cpu_percent(interval=0.4):.0f}%", f"RAM {psutil.virtual_memory().percent:.0f}%"
             f" ({psutil.virtual_memory().used / 2**30:.1f}/{psutil.virtual_memory().total / 2**30:.1f} GB)"]
    try:
        d = psutil.disk_usage(os.path.abspath(os.sep))
        parts.append(f"system disk {d.percent:.0f}% full ({d.free / 2**30:.0f} GB free)")
    except Exception:
        pass
    b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if b:
        parts.append(f"battery {b.percent:.0f}% ({'charging' if b.power_plugged else 'on battery'})")
    if shutil.which("nvidia-smi"):
        try:
            g = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                                "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                               creationflags=NO_WINDOW).stdout.strip().splitlines()[0].split(", ")
            parts.append(f"GPU {g[0]} at {g[1]}% load, {g[2]}/{g[3]} MB VRAM, {g[4]}°C")
        except Exception:
            pass
    up = time.time() - psutil.boot_time()
    parts.append(f"uptime {int(up // 3600)}h {int(up % 3600 // 60)}m")
    return "; ".join(parts) + "."


@tool("get_datetime", "Get the current local date, time and day.", "Time", "🕒")
def get_datetime() -> str:
    n = dt.datetime.now()
    return n.strftime("It's %I:%M %p, %A %d %B %Y.").replace(" 0", " ")


WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
       66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
       80: "rain showers", 81: "heavy showers", 82: "violent showers", 85: "snow showers", 86: "snow showers",
       95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail"}


@tool("get_weather", "Current weather and today's/tomorrow's forecast for a city (default: the user's home city).", "Weather", "⛅",
      city=("string", "City name (optional)", False), day=("string", "today or tomorrow", False, ["today", "tomorrow"]))
def get_weather(city: Optional[str] = None, day: Optional[str] = "today") -> str:
    city = city or (CTX.settings.home_city if CTX.settings else "Mumbai")
    g = json.loads(_http_get("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(city)))
    if not g.get("results"):
        return f"Error: couldn't find a place called {city}."
    r = g["results"][0]
    url = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&timezone=auto"
           "&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m"
           "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code").format(
        lat=r["latitude"], lon=r["longitude"])
    w = json.loads(_http_get(url))
    c, d = w["current"], w["daily"]
    i = 1 if day == "tomorrow" else 0
    place = f"{r['name']}, {r.get('country', '')}".strip(", ")
    now = (f"Now in {place}: {c['temperature_2m']:.0f}°C (feels {c['apparent_temperature']:.0f}°C), "
           f"{WMO.get(c['weather_code'], 'unknown')}, humidity {c['relative_humidity_2m']}%, wind {c['wind_speed_10m']:.0f} km/h. ")
    fc = (f"{'Tomorrow' if i else 'Today'}: {WMO.get(d['weather_code'][i], '')}, {d['temperature_2m_min'][i]:.0f}–"
          f"{d['temperature_2m_max'][i]:.0f}°C, {d['precipitation_probability_max'][i] or 0}% chance of rain.")
    return (now if i == 0 else "") + fc


@tool("take_screenshot", "Take a screenshot of all monitors and save it to Pictures/Screenshots.", "Screenshot", "📸")
def take_screenshot() -> str:
    folder = Path.home() / "Pictures" / "Screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Zoha_{dt.datetime.now():%Y%m%d_%H%M%S}.png"
    if not WIN:
        return "Error: screenshots are Windows-only for now."
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
        "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size);"
        "$bmp.Save($env:ZOHA_SHOT,[System.Drawing.Imaging.ImageFormat]::Png);$g.Dispose();$bmp.Dispose()"
    )
    _ps(script, env={"ZOHA_SHOT": str(path)})
    return f"Screenshot saved as {path.name} in Pictures/Screenshots." if path.exists() else "Error: screenshot failed."


@tool("lock_pc", "Lock the computer.", "Lock PC", "🔒")
def lock_pc() -> str:
    if WIN:
        ctypes.windll.user32.LockWorkStation()
        return "Locked."
    return "Error: lock is Windows-only."


_POWER_PENDING: Dict[str, float] = {}
YES_RX = re.compile(r"^\W*(?:yes|yeah|yep|yup|sure|ok(?:ay)?|confirm(?:ed)?|do it|go ahead|please do|absolutely|"
                    r"yes,? (?:please|do it|go ahead|shut ?(?:it )?down|restart(?: it)?|sleep|confirm(?:ed)?))\b[\w\s,.!']*$", re.I)


@tool("power", "Shut down, restart or sleep the PC, or cancel a pending shutdown. Call it when the user asks; Zoha will ask them to "
      "confirm and only act after they say yes in their NEXT message. 'You can sleep' / 'that's all' is about YOU, not the PC.",
      "Power", "⏻", action=("string", "Power action", True, ["shutdown", "restart", "sleep", "cancel"]))
def power(action: str, **_ignored) -> str:
    if action == "cancel":
        if WIN:
            subprocess.run(["shutdown", "/a"], creationflags=NO_WINDOW)
        _POWER_PENDING.clear()
        return "Cancelled the pending shutdown."
    if action not in ("shutdown", "restart", "sleep"):
        return "Error: unknown power action."
    now = time.time()
    asked = _POWER_PENDING.get(action)
    said_yes = bool(YES_RX.match(CTX.last_user_text or ""))
    if not (asked and CTX.turn_started > asked and now - asked < 120 and said_yes):
        _POWER_PENDING.clear()
        _POWER_PENDING[action] = now
        word = {"shutdown": "shut down", "restart": "restart", "sleep": "put to sleep"}[action]
        return f"NOT DONE YET. Ask the user exactly: 'Should I {word} the PC? Say yes to confirm.' Do nothing else."
    _POWER_PENDING.clear()
    if not WIN:
        return "Error: power actions are Windows-only."
    if action == "shutdown":
        subprocess.run(["shutdown", "/s", "/t", "20"], creationflags=NO_WINDOW)
        return "Shutting down in 20 seconds. Say 'cancel shutdown' to stop it."
    if action == "restart":
        subprocess.run(["shutdown", "/r", "/t", "20"], creationflags=NO_WINDOW)
        return "Restarting in 20 seconds. Say 'cancel shutdown' to stop it."
    subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], creationflags=NO_WINDOW)
    return "Putting the PC to sleep."


def pending_power() -> Optional[str]:
    """The power action waiting for the user's yes (asked within the last 2 minutes)."""
    for a, t in _POWER_PENDING.items():
        if time.time() - t < 120:
            return a
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Files & folders
# ──────────────────────────────────────────────────────────────────────────────
KNOWN = {"downloads": "Downloads", "documents": "Documents", "desktop": "Desktop", "pictures": "Pictures",
         "photos": "Pictures", "videos": "Videos", "music": "Music", "screenshots": "Pictures/Screenshots", "home": ""}


@tool("open_folder", "Open a folder in File Explorer: a known folder (downloads, documents, desktop, pictures, videos, music, screenshots) or a full path like D:/Zhessor.",
      "Open folder", "📁", folder=("string", "Known folder name or path", True))
def open_folder(folder: str) -> str:
    f = folder.strip().strip('"')
    key = f.lower().removeprefix("my ").strip()
    p = Path.home() / KNOWN[key] if key in KNOWN else Path(os.path.expandvars(os.path.expanduser(f)))
    if not p.exists():
        return f"Error: folder not found: {p}"
    _open(str(p))
    return f"Opened {p}."


SEARCH_ROOTS = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "OneDrive"]
SPOKEN_FILE = [(r"\s*\b(?:underscore|under score)\b\s*", "_"), (r"\s*\b(?:dot|point)\b\s*", "."),
               (r"\s*\b(?:dash|hyphen)\b\s*", "-"), (r"\s*\bin (?:the )?brackets? (\w+)", r" (\1)"),
               (r"\s*\bbrackets? (\w+)", r" (\1)")]
NUM_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "to": "2", "too": "2"}


def spoken_name(text: str) -> str:
    """'gym underscore website in the bracket two dot html' → 'gym_website (2).html'."""
    t = (text or "").strip().strip("'\"")
    for rx, rep in SPOKEN_FILE:
        t = re.sub(rx, rep, t, flags=re.I)
    t = re.sub(r"\((\w+)\)", lambda m: "(" + NUM_WORDS.get(m.group(1).lower(), m.group(1)) + ")", t)
    return t.strip()


def _sound(w: str) -> str:
    """Rough sound-alike key so speech mix-ups still match: jim≈gym, kafe≈cafe, foto≈photo."""
    w = w.lower()
    for a_, b_ in (("ph", "f"), ("ck", "k"), ("q", "k"), ("x", "ks"), ("z", "s"), ("y", "i"), ("c", "k"), ("ee", "i"), ("oo", "u")):
        w = w.replace(a_, b_)
    return re.sub(r"^j", "g", w)


def find_named(name: str, exts: tuple = (), roots=("Desktop", "Documents", "Downloads")) -> Optional[Path]:
    """Best match for a (possibly mis-heard) file name: exact, then all words present, then fuzzy words
    ('jim website' finds gym_website.html), newest first."""
    import difflib
    name = spoken_name(name)
    p = Path(name)
    if p.is_absolute() and p.exists():
        return p
    want = [w for w in re.split(r"[\s_\-.()]+", Path(name).stem.lower()) if w and not w.isdigit()]
    num = re.search(r"\((\d+)\)", name)
    best, best_key = None, None
    for r in roots:
        d = Path.home() / r
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if not f.is_file() or (exts and f.suffix.lower() not in exts):
                continue
            if f.name.lower() == Path(name).name.lower():
                return f
            have = [w for w in re.split(r"[\s_\-.()]+", f.stem.lower()) if w and not w.isdigit()]
            if not want or not have:
                continue
            hits = sum(1 for w in want if w in have or any(difflib.SequenceMatcher(None, _sound(w), _sound(h)).ratio() >= 0.66
                                                            for h in have))
            if hits < max(1, len(want) - (1 if len(want) > 2 else 0)):
                continue
            same_num = bool(num) and f"({num.group(1)})" in f.name
            key = (hits, same_num, f.stat().st_mtime)
            if best_key is None or key > best_key:
                best, best_key = f, key
    return best


@tool("find_files", "Search the user's Desktop/Documents/Downloads/Pictures/Videos/Music (and D:/ projects) for files or folders by name. Returns paths.",
      "Find files", "🗂", query=("string", "Part of the file/folder name", True),
      open_first=("boolean", "Open the best match", False))
def find_files(query: str = "", open_first: bool = False) -> str:
    q = spoken_name(query or "").lower().strip()
    qtoks = [t for t in re.split(r"[\s_\-.()]+", q) if t and t not in ("file", "files", "the", "my", "on", "desktop")]
    if not qtoks:   # "show me the files on my desktop" → newest first, numbered, so the user can say "open number 3"
        desk = Path.home() / "Desktop"
        files = sorted([f for f in desk.iterdir() if not f.name.startswith(".") and f.name.lower() != "desktop.ini"],
                       key=lambda f: f.stat().st_mtime, reverse=True)[:15] if desk.is_dir() else []
        CTX.last_listing = [str(f) for f in files]
        return ("Newest on the Desktop:\n" + "\n".join(f"{i}. {f.name}" for i, f in enumerate(files, 1))) if files else "The Desktop is empty."
    roots = [Path.home() / r for r in SEARCH_ROOTS] + ([Path("D:/")] if WIN and Path("D:/").exists() else [])
    hits, deadline = [], time.time() + 4.0
    skip = {"node_modules", ".git", "venv", ".venv", "__pycache__", "AppData", ".next", "dist", "build", "$RECYCLE.BIN", "System Volume Information"}
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
            depth = len(Path(dirpath).relative_to(root).parts)
            if depth > 5:
                dirnames[:] = []
            for n in dirnames + filenames:
                nl = n.lower()
                if all(t in nl for t in qtoks):
                    full = os.path.join(dirpath, n)
                    score = (nl.startswith(qtoks[0]), -len(nl), os.path.getmtime(full) if os.path.exists(full) else 0)
                    hits.append((score, full))
            if time.time() > deadline:
                break
        if time.time() > deadline:
            break
    if not hits:
        return f"No files matching '{query}'."
    hits.sort(reverse=True)
    paths = [h[1] for h in hits[:6]]
    CTX.last_listing = paths
    if open_first:
        _open(paths[0])
        return f"Opened {paths[0]}. Other matches: " + "; ".join(paths[1:4])
    return "Matches:\n" + "\n".join(paths)


@tool("open_path", "Open a specific file or folder path that you already know (e.g. from find_files).", "Open file", "📄",
      path=("string", "Absolute path", True))
def open_path(path: str) -> str:
    p = (path or "").strip()
    m = re.fullmatch(r"(?:number |no\.? ?|#)?(\d{1,2})", p.lower())
    if m and CTX.last_listing and 1 <= int(m.group(1)) <= len(CTX.last_listing):
        path = CTX.last_listing[int(m.group(1)) - 1]
    elif p.lower() in ("it", "that", "this", "the file", "last", "the page") and CTX.last_file:
        path = str(CTX.last_file)
    if not os.path.exists(path):   # wrong folder or a guessed path ("C:/Users/<someone>/Desktop/x.html") – look it up by name
        found = find_named(Path(spoken_name(path)).name)
        if not found:
            return f"Error: couldn't find {Path(path).name} on the Desktop, Documents or Downloads."
        path = str(found)
    _open(path)
    return f"Opened {os.path.basename(path) or path}."


NOTES = Path.home() / "Documents" / "Zoha_Notes" / "Quick_Notes.md"


@tool("create_note", "Save a quick note / to-do for the user.", "Note saved", "📝", text=("string", "The note", True))
def create_note(text: str) -> str:
    NOTES.parent.mkdir(parents=True, exist_ok=True)
    with open(NOTES, "a", encoding="utf-8") as f:
        f.write(f"- [{dt.datetime.now():%d %b %Y %H:%M}] {text.strip()}\n")
    return f"Noted: {text.strip()}"


@tool("read_notes", "Read back the user's most recent quick notes.", "Read notes", "📒",
      count=("integer", "How many recent notes (default 5)", False))
def read_notes(count: int = 5) -> str:
    if not NOTES.exists():
        return "No notes yet."
    lines = [l.strip() for l in NOTES.read_text(encoding="utf-8").splitlines() if l.strip().startswith("-")]
    return "\n".join(lines[-max(1, int(count)):]) or "No notes yet."


# ──────────────────────────────────────────────────────────────────────────────
# Keyboard & clipboard
# ──────────────────────────────────────────────────────────────────────────────
@tool("type_text", "Type a SHORT piece of text (a line or two) into the window in front, like dictation. "
      "Never use it for code, letters, documents or anything long – use write_file for those.", "Type text", "⌨",
      text=("string", "Exact text to type (short)", True))
def type_text(text: str) -> str:
    if not WIN:
        return "Error: typing is Windows-only."
    if len(text) > 400 or text.count("\n") > 4:
        return ("Error: too long to type safely. Use write_file to save it as a file and open it "
                "(e.g. write_file(filename='landing.html', what='…')).")
    target = _focus_target()
    if not target:
        return "Error: no window to type into (only Zoha's own window is open). Open the app first."
    time.sleep(0.3)
    if not _foreground_is_other():
        return "Error: couldn't bring the target window to the front, so I didn't type anything."
    _send_unicode(text)
    return f"Typed {len(text)} characters into {target}."


def _foreground_pid() -> int:
    from ctypes import wintypes
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.windll.user32.GetForegroundWindow(), ctypes.byref(pid))
    return pid.value


def _foreground_is_other() -> bool:
    """True when the window in front is not Zoha herself (her GUI runs in this same process)."""
    return _foreground_pid() not in (0, os.getpid())


def _focus_target() -> Optional[str]:
    """Make sure keystrokes go to the user's app, never into Zoha's own chat box (that once sent her own
    text back to her as commands). If Zoha is in front, bring the most recent other window forward."""
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    if _foreground_is_other():
        n = user32.GetWindowTextLengthW(user32.GetForegroundWindow())
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(user32.GetForegroundWindow(), buf, n + 1)
        return buf.value or "the window in front"
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4) or user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        n = user32.GetWindowTextLengthW(hwnd)
        if pid.value == os.getpid() or n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value in ("Program Manager", "Microsoft Text Input Application", "Windows Input Experience"):
            return True
        found.append((hwnd, buf.value))
        return False   # z-order: the first one is the most recently used

    user32.EnumWindows(cb, 0)
    if not found:
        return None
    hwnd, title = found[0]
    user32.keybd_event(0x12, 0, 0, 0)          # tap Alt so Windows allows the focus change
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x12, 0, 2, 0)
    return title


CODE_EXT = {"py", "js", "ts", "jsx", "tsx", "css", "java", "c", "cpp", "cs", "go", "rs", "php", "sql", "sh", "json"}

WEB_BRIEF = """Rules for this page (Zhessor quality, Mumbai/India audience):
- One self-contained file: CSS in <style>, JS in <script>, no frameworks, no external JS.
- India: prices in ₹ with Indian formatting (₹1,499), +91 phone format, Indian place names; copyright {year}.
- Real, specific copy written for THIS business – no lorem ipsum, no "Welcome to our site", no generic slogans.
- Distinctive look chosen for this business: a deliberate Google Fonts pairing (not Helvetica/Arial), a palette
  of 4–5 named CSS variables that fits the brand, generous spacing, clear type scale.
- Sections the business actually needs (e.g. hero with one clear call to action, offerings, why us/story,
  testimonials, location/contact with WhatsApp button, footer).
- Mobile first: a working hamburger menu (toggle with aria-expanded), nothing hidden without a replacement,
  tap targets ≥ 44px, images with width/height and loading="lazy".
- Images: use https://picsum.photos/seed/<word>/800/600 placeholders with honest alt text (no fake product photos).
- No alert()/prompt(): show inline messages instead (e.g. "Thanks, we'll be in touch").
- Accessible: semantic tags, labels on inputs, visible focus styles, colour contrast ≥ 4.5:1,
  prefers-reduced-motion respected. Keep animations subtle."""

CODE_BRIEF = """Rules: complete, runnable code (no "..." or TODO stubs), clear names, short comments only where
the logic isn't obvious, handle the obvious errors, no secrets or API keys in the code, Windows-friendly paths."""

TEXT_BRIEF = """Rules: write it ready to use – clear structure, plain natural English (or the language asked for),
Indian context where relevant (₹, Indian date format), no placeholder brackets unless a detail is truly unknown."""


SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.S)


def skill_text(text: str) -> str:
    """Skills are Markdown files with a small `name` / `description` header (the SKILL.md layout). The model only needs the body."""
    return FRONTMATTER.sub("", text, count=1).lstrip()


def skill_meta(text: str) -> dict:
    """The header fields of a skill file, e.g. {'name': 'email', 'description': '...'}."""
    m = FRONTMATTER.match(text)
    out = {}
    for line in (m.group(0).splitlines()[1:-1] if m else []):
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _skill(kind: str, fallback: str) -> tuple:
    """(full skill, checklist) from skills/<kind>.md – plain markdown you can edit to teach Zoha your standards."""
    year = str(dt.date.today().year)
    try:
        text = skill_text((SKILLS_DIR / f"{kind}.md").read_text(encoding="utf-8")).replace("{year}", year)
    except Exception:
        text = fallback.replace("{year}", year)
    m = re.search(r"^## Checklist.*", text, re.M | re.S)
    return text, (m.group(0) if m else text)


def lint_html(html: str) -> list:
    """Concrete, checkable problems in a generated page (each one becomes a fix instruction)."""
    low, out = html.lower(), []
    css = " ".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I))
    before_media = css.split("@media")[0]
    if re.search(r"\.(menu|nav-links)\s*\{[^}]*display\s*:\s*none", before_media):
        out.append("The nav menu is hidden with display:none outside the @media query, so desktop has no navigation. "
                   "Show it as display:flex by default and hide it only inside @media (max-width: 760px).")
    if "wa.me/" not in low:
        out.append("Add a floating WhatsApp button: <a class=\"wa-float\" href=\"https://wa.me/9198XXXXXXXX?text=Hi\">WhatsApp us</a> with fixed position bottom-right.")
    if re.search(r"outline\s*:\s*(none|0)", css) and ":focus-visible" not in css:
        out.append("Inputs/buttons use outline:none – add a visible :focus-visible style (outline: 3px solid var(--accent)).")
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    if imgs and 'loading="lazy"' in imgs[0]:
        out.append('The first (hero) image must not be lazy: replace loading="lazy" with fetchpriority="high" on it.')
    if any(("alt=" not in i) or ("width=" not in i) for i in imgs):
        out.append("Every <img> needs alt, width and height attributes.")
    if re.search(r"\b(alert|prompt|confirm)\s*\(", html):
        out.append("Remove alert()/prompt()/confirm() – show an inline message in the page instead.")
    if "display:contents" in low.replace(" ", ""):
        out.append("Remove display:contents from the container; give the section a normal .container inside it.")
    if len(re.findall(r'\sstyle="', html)) > 2:
        out.append("Move the inline style=\"…\" attributes into CSS classes.")
    if re.search(r"\$\s?\d", re.sub(r"<script.*?</script>", "", html, flags=re.S)):
        out.append("Prices must be in ₹ with Indian grouping (₹1,499), not $.")
    if re.search(r"lorem ipsum|welcome to our (web)?site", low):
        out.append("Replace placeholder/generic text with specific copy for this business.")
    year = str(dt.date.today().year)
    if ("©" in html or "&copy;" in low) and year not in html:
        out.append(f"The copyright year must be {year}.")
    ids = set(re.findall(r'<(?:input|textarea|select)\b[^>]*\bid="([^"]+)"', html))
    labelled = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', html))
    if ids - labelled:
        out.append("Every input/textarea needs a <label for=\"…\">: missing for " + ", ".join(sorted(ids - labelled)) + ".")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    blocks = set()   # selectors of whole page areas: <section>/<footer>/<header> ids and classes
    for tag in re.findall(r"<(?:section|footer|header|aside)\b[^>]*>", html, re.I):
        blocks |= {"#" + i for i in re.findall(r'\bid="([^"]+)"', tag)}
        for cl in re.findall(r'\bclass="([^"]+)"', tag):
            blocks |= {"." + c for c in cl.split()}
    blocks |= {"footer", "section"}
    root = dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", css))

    def dark(v):
        v = v.strip()
        m = re.match(r"var\(--([\w-]+)\)", v)
        v = root.get(m.group(1), "").strip() if m else v
        h = re.match(r"#([0-9a-f]{3}|[0-9a-f]{6})\b", v, re.I)
        if not h:
            return False
        h = h.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b < 90
    p_dark = any(re.fullmatch(r"\s*p\s*", sel) and re.search(r"(?<!-)color\s*:", body) for sel, body in rules)
    for sel, body in rules:
        bg = re.search(r"background(?:-color)?\s*:\s*([^;]+)", body)
        sel = sel.strip()
        if bg and dark(bg.group(1)) and p_dark and sel in blocks:
            if not any(s2.strip().startswith(sel + " ") and " p" in s2 for s2, _ in rules):
                out.append(f"Paragraphs inside '{sel}' use the global grey text colour on a dark background – add "
                           f"'{sel} p {{ color: rgba(255,255,255,.8); }}'.")
    ids_all = set(re.findall(r'\bid="([^"]+)"', html))
    dead = sorted({h for h in re.findall(r'href="#([^"]+)"', html) if h not in ids_all})
    if dead:
        out.append("These links point to sections that don't exist: " + ", ".join("#" + d for d in dead)
                   + ". Add the sections (with those ids) or remove the links.")
    left = sorted({w for w in re.findall(
        r"\b(BUSINESS|AREA|Specific promise[^<]*|Offering name|Short, believable review|Offer line for[^<]*|Trust signal|"
        r"Fact about them|Milestone in one line|Package name|What's included|Project or item|Step name|Question customers really ask|"
        r"Full name|Highlight one|Highlight two|Second highlight|Primary action|One specific line[^<]*|Two sentences of real[^<]*|"
        r"Two specific lines[^<]*|One line about[^<]*|One line with the offer[^<]*|Who runs it, since when[^<]*|Landmark-style directions[^<]*|"
        r"Slide title[^<]*|Tab (?:one|two|three)|Category name|Brand name|Service name|Value name|Proprietor name|Branch name|"
        r"Town (?:one|two)|hello@example\.in|Slide (?:one|two|three) photo|Who they are, in one strong line|"
        r"A clear closing line[^<]*|e\.g\. \"[^<]*)", html)})
    if left:
        out.append("Starter placeholders are still in the page – replace them with real content: " + ", ".join(left[:4]))
    since = re.search(r"\bsince\s+((?:19|20)\d\d)\b", html, re.I)
    yrs = re.search(r">\s*(\d{1,3})\+?\s*(?:yrs|years)\b", html, re.I)
    if since and yrs and abs((dt.date.today().year - int(since.group(1))) - int(yrs.group(1))) > 1:
        out.append(f"'Since {since.group(1)}' and '{yrs.group(1)} yrs' don't match – it's {dt.date.today().year - int(since.group(1))} years; make them agree.")
    if "<title>" not in low:
        out.append("Add a <title> like 'Business – what they do in Area, City' (under 60 characters).")
    if 'name="description"' not in low:
        out.append("Add <meta name=\"description\" content=\"…\"> with 140–160 characters of specific text about the business.")
    if 'property="og:title"' not in low:
        out.append("Add Open Graph tags (og:title, og:description, og:type) so WhatsApp link previews look good.")
    if "application/ld+json" not in low:
        out.append("Add a <script type=\"application/ld+json\"> LocalBusiness block with name, address (addressCountry IN), telephone and openingHours.")
    if "</html>" not in low:
        out.append("The file is cut off – finish it and end with </html>.")
    return out


def _lum(hexcol: str) -> float:
    h = hexcol.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(a: str, b: str, t: float) -> str:
    """t of colour b mixed into a (hex)."""
    ha, hb = a.lstrip("#"), b.lstrip("#")
    ha = "".join(c * 2 for c in ha) if len(ha) == 3 else ha
    hb = "".join(c * 2 for c in hb) if len(hb) == 3 else hb
    return "#" + "".join(f"{round(int(ha[i:i + 2], 16) * (1 - t) + int(hb[i:i + 2], 16) * t):02x}" for i in (0, 2, 4))


def _fix_contrast(html: str) -> str:
    """Models love pale gold/pastel brand colours with white text. Keep their palette, but make it readable (WCAG 4.5:1)."""
    var = dict(re.findall(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\b", html))
    paper, ink = var.get("paper", "#ffffff"), var.get("ink", "#111111")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}", paper) or not re.fullmatch(r"#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}", ink):
        return html
    fixes = {}
    brand, on = var.get("brand"), var.get("on-brand")
    if brand and on and _contrast(brand, on) < 4.5:
        fixes["on-brand"] = max(("#111111", "#ffffff"), key=lambda c: _contrast(brand, c))
    for name in ("heading", "muted"):
        c = var.get(name)
        if c and _contrast(c, paper) < 4.5:
            t, new = 0.0, c
            while _contrast(new, paper) < 4.5 and t < 1:
                t += 0.1
                new = _mix(c, ink, t)
            fixes[name] = new
    for name, val in fixes.items():
        html = re.sub(r"(--" + re.escape(name) + r"\s*:\s*)#[0-9a-fA-F]{3,6}\b", lambda m: m.group(1) + val, html)
    # headings hard-coded to a colour that fails on the page background
    m = re.search(r"h1\s*,\s*h2\s*,\s*h3\s*\{[^}]*?color\s*:\s*(#[0-9a-fA-F]{3,6})", html)
    if m and _contrast(m.group(1), paper) < 4.5:
        html = html.replace(m.group(0), m.group(0)[: -len(m.group(1))] + "var(--heading)")
    return html


MOTION_CSS = """
    /* zoha-motion: reveal on scroll, header shadow, active menu link, phone action bar */
    .reveal { opacity: 0; transform: translateY(18px); transition: opacity .6s ease, transform .6s ease; }
    .reveal.in { opacity: 1; transform: none; }
    header.scrolled { box-shadow: 0 6px 20px rgba(0,0,0,.08); }
    #menu a[aria-current="true"] { text-decoration: underline; text-underline-offset: 6px; text-decoration-thickness: 2px; }
    .m-bar { display: none; }
    @media (max-width: 760px) {
      .m-bar { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; position: fixed; left: .6rem; right: .6rem; bottom: .6rem; z-index: 60; }
      .m-bar a { min-height: 50px; display: flex; align-items: center; justify-content: center; border-radius: 999px; font-weight: 800; text-decoration: none; box-shadow: 0 8px 22px rgba(0,0,0,.2); }
      .m-bar .call { background: var(--brand, #222); color: var(--on-brand, #fff); }
      .m-bar .wa { background: #25D366; color: #053d1c; }
      .wa-float { display: none !important; }
      body { padding-bottom: 76px; }
    }
    @media (max-width: 420px) { .cta .btn { flex: 1 1 100%; justify-content: center; } }
    /* motion personalities – one per page (body[data-motion]) + a few shared touches */
    .zoha-progress { position: fixed; top: 0; left: 0; height: 3px; width: 100%; transform-origin: 0 50%; transform: scaleX(0);
                    background: linear-gradient(90deg, var(--brand-2, #888), var(--accent, #aaa)); z-index: 70; pointer-events: none; }
    #menu a:not(.btn) { background: linear-gradient(currentColor, currentColor) 0 100% / 0 2px no-repeat; transition: background-size .3s ease; }
    #menu a:not(.btn):hover { background-size: 100% 2px; }
    .price { background-size: 220% 100%; }
    .item:hover .price, .tile:hover .price, .row:hover .price { animation: shimmer 1.1s ease; }
    @keyframes shimmer { from { background-image: linear-gradient(110deg, transparent 30%, rgba(255,255,255,.6) 50%, transparent 70%); background-position: 120% 0; }
                         to { background-image: linear-gradient(110deg, transparent 30%, rgba(255,255,255,.6) 50%, transparent 70%); background-position: -120% 0; } }
    .art { transition: transform .5s ease, box-shadow .5s ease; }
    .art:hover { transform: scale(1.02); }
    [data-motion="float"] .hero .art, [data-motion="float"] .hero-art .badge { animation: bob 6s ease-in-out infinite alternate; }
    [data-motion="float"] .hero .art:nth-child(2n) { animation-duration: 7.5s; animation-delay: -2s; }
    @keyframes bob { from { translate: 0 0; } to { translate: 0 -14px; } }
    .zoha-word { display: inline-block; opacity: 0; transform: translateY(.45em); animation: word .7s cubic-bezier(.2,.7,.2,1) forwards; }
    @keyframes word { to { opacity: 1; transform: none; } }
    [data-motion="words"] .hero h1 { animation: none; }
    .zoha-mesh { position: absolute; inset: -20%; z-index: 0; pointer-events: none; opacity: .55; filter: blur(40px);
                background: radial-gradient(30% 35% at 20% 30%, var(--brand-2, #888), transparent 70%),
                            radial-gradient(28% 30% at 80% 20%, var(--accent, #aaa), transparent 70%),
                            radial-gradient(35% 35% at 60% 85%, var(--brand, #666), transparent 70%);
                animation: drift 18s ease-in-out infinite alternate; }
    @keyframes drift { 0% { transform: translate(0,0) rotate(0deg); } 50% { transform: translate(4%,-3%) rotate(8deg); } 100% { transform: translate(-3%,4%) rotate(-6deg); } }
    [data-motion="drift"] .hero, [data-motion="glow"] .hero { position: relative; overflow: hidden; }
    [data-motion="drift"] .hero > :not(.zoha-mesh), [data-motion="glow"] .hero > :not(.zoha-glow) { position: relative; z-index: 1; }
    .zoha-glow { position: absolute; width: 460px; height: 460px; left: 0; top: 0; border-radius: 50%; pointer-events: none; z-index: 0;
                background: radial-gradient(circle, color-mix(in srgb, var(--accent, #fff) 45%, transparent), transparent 65%);
                transform: translate(-50%,-50%); transition: opacity .4s ease; opacity: 0; }
    .hero:hover .zoha-glow { opacity: .75; }
    @media (prefers-reduced-motion: reduce) {
      .reveal { opacity: 1 !important; transform: none !important; }
      .zoha-word { opacity: 1 !important; transform: none !important; animation: none !important; }
      .zoha-mesh, .zoha-glow, .zoha-progress { display: none !important; }
    }
"""

MOTION_JS = r"""<script>/* zoha-motion */
(() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fine = matchMedia('(pointer: fine)').matches;
  const header = document.querySelector('header');
  const hero = document.querySelector('.hero');
  const styles = ['float', 'words', 'drift', 'glow'];
  if (!document.body.dataset.motion) {   // pick one personality per page (stable for the same title)
    let h = 0; for (const c of document.title) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    document.body.dataset.motion = styles[h % styles.length];
  }
  if (document.body.dataset.motion === 'float' && !(hero && hero.querySelector('.art'))) document.body.dataset.motion = 'words';
  const motion = document.body.dataset.motion;
  const bar = document.createElement('div'); bar.className = 'zoha-progress'; document.body.appendChild(bar);
  const arts = hero ? [...hero.querySelectorAll('.art')] : [];
  addEventListener('scroll', () => {
    header && header.classList.toggle('scrolled', scrollY > 10);
    const max = document.documentElement.scrollHeight - innerHeight;
    bar.style.transform = `scaleX(${max > 0 ? scrollY / max : 0})`;
    if (!reduce && motion === 'float') arts.forEach((a, i) => a.style.transform = `translateY(${-scrollY * (0.04 + i * 0.03)}px)`);
  }, { passive: true });
  if (!reduce && hero) {
    const h1 = hero.querySelector('h1');
    if (motion === 'words' && h1 && !h1.children.length) {
      const words = h1.textContent.trim().split(/\s+/);
      h1.textContent = '';
      words.forEach((w, i) => { const s = document.createElement('span'); s.className = 'zoha-word'; s.textContent = w;
        s.style.animationDelay = (i * 90) + 'ms'; h1.append(s, ' '); });
    }
    if (motion === 'drift') { const m = document.createElement('div'); m.className = 'zoha-mesh'; m.setAttribute('aria-hidden', 'true'); hero.prepend(m); }
    if (motion === 'glow' && fine) {
      const g = document.createElement('div'); g.className = 'zoha-glow'; g.setAttribute('aria-hidden', 'true'); hero.prepend(g);
      hero.addEventListener('pointermove', e => { const r = hero.getBoundingClientRect(); g.style.left = (e.clientX - r.left) + 'px'; g.style.top = (e.clientY - r.top) + 'px'; });
    }
  }
  if (!reduce && fine) {   // gentle 3D tilt on cards (mouse only)
    document.querySelectorAll('.item, .tile, .plan:not(.featured), .person').forEach(c => {
      c.addEventListener('pointermove', e => { const r = c.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
        c.style.transform = `perspective(700px) rotateX(${(-y * 6).toFixed(2)}deg) rotateY(${(x * 6).toFixed(2)}deg) translateY(-4px)`; });
      c.addEventListener('pointerleave', () => c.style.transform = '');
    });
  }
  if (!('IntersectionObserver' in window)) return;
  if (!reduce) {
    const els = document.querySelectorAll('main section h2, .item, .tile, .plan, .row, .alt-row, .review, .wall blockquote, .facts li, .stat, .person, .steps li, .dlist li, .gallery .art, .tl li');
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), { threshold: .12 });
    els.forEach((el, i) => { el.classList.add('reveal'); el.style.transitionDelay = (i % 4) * 70 + 'ms'; io.observe(el); });
    const nums = document.querySelectorAll('.stat strong');
    const co = new IntersectionObserver(es => es.forEach(e => {
      if (!e.isIntersecting) return; co.unobserve(e.target);
      const el = e.target, m = el.textContent.match(/^([\d,.]+)(.*)$/s); if (!m) return;
      const end = parseFloat(m[1].replace(/,/g, '')), dec = (m[1].split('.')[1] || '').length, t0 = performance.now();
      const step = now => { const k = Math.min(1, (now - t0) / 1200), v = end * (1 - Math.pow(1 - k, 3));
        el.textContent = v.toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec }) + m[2];
        if (k < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    }), { threshold: .5 });
    nums.forEach(n => co.observe(n));
  }
  const links = [...document.querySelectorAll('#menu a[href^="#"]')];
  const so = new IntersectionObserver(es => es.forEach(e => {
    if (!e.isIntersecting) return;
    links.forEach(a => a.setAttribute('aria-current', a.getAttribute('href') === '#' + e.target.id ? 'true' : 'false'));
  }), { rootMargin: '-45% 0px -50% 0px' });
  links.forEach(a => { const s = document.querySelector(a.getAttribute('href')); if (s) so.observe(s); });
})();
</script>"""


def _head_upgrades(html: str) -> str:
    """Small touches real sites have: a favicon in the brand colour, mobile browser bar colour, skip-to-content link."""
    brand = re.search(r"--brand\s*:\s*(#[0-9a-fA-F]{6})", html)
    title = re.search(r"<title>\s*(.*?)\s*</title>", html, re.S | re.I)
    if brand and "rel=\"icon\"" not in html and "</head>" in html:
        letter = (re.sub(r"^(the|a)\s+", "", title.group(1), flags=re.I)[:1] if title else "•").upper()
        letter = letter if letter.isalnum() else "•"
        col = brand.group(1).replace("#", "%23")
        icon = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='14' "
                f"fill='{col}'/><text x='32' y='44' font-size='36' text-anchor='middle' fill='white' font-family='Arial' font-weight='700'>{letter}</text></svg>")
        html = html.replace("</head>", f'  <link rel="icon" href="{icon}">\n  <meta name="theme-color" content="{brand.group(1)}">\n</head>', 1)
    if "skip-link" not in html and re.search(r"<main\b", html) and "<body" in html:
        html = re.sub(r"<main\b(?![^>]*\bid=)", '<main id="main"', html, count=1)
        html = re.sub(r"(<body[^>]*>)", r'\1\n  <a class="skip-link" href="#main">Skip to content</a>', html, count=1)
        i = html.lower().rfind("</style>")
        if i > 0:
            html = html[:i] + ("    .skip-link { position: absolute; left: -999px; top: 0; z-index: 100; background: #fff; color: #111; padding: .6rem 1rem; }\n"
                               "    .skip-link:focus { left: 1rem; top: 1rem; }\n  ") + html[i:]
    return html


def _add_motion(html: str) -> str:
    if "zoha-motion" in html or "</body>" not in html:
        return html
    tel = re.search(r'href="(tel:[^"]+)"', html)
    wa = re.search(r'href="(https://wa\.me/[^"]+)"', html)
    bar = ""
    if tel and wa:
        bar = (f'\n  <div class="m-bar"><a class="call" href="{tel.group(1)}">Call now</a>'
               f'<a class="wa" href="{wa.group(1)}">WhatsApp</a></div>')
    i = html.lower().rfind("</style>")
    if i < 0:
        return html
    html = html[:i] + MOTION_CSS + "  " + html[i:]
    j = html.lower().rfind("</body>")
    return html[:j] + bar + "\n  " + MOTION_JS + "\n" + html[j:]


def autofix_html(html: str) -> str:
    """Deterministic repairs no model should be trusted with (safe to run any number of times)."""
    if "<html" not in html.lower():
        return html
    try:
        html = _fix_contrast(html)
    except Exception:
        pass
    html = _add_motion(html)
    html = _head_upgrades(html)
    try:
        from .web3d import add_3d
        html = add_3d(html)
    except Exception:
        pass
    html = re.sub(r"\s*/\*\s*(fixed|fix|changed|updated)\b[^*]*\*/", "", html, flags=re.I)      # "/* Fixed: … */"
    html = re.sub(r"\s*<!--\s*(fixed|fix|changed|updated)\b.*?-->", "", html, flags=re.I | re.S)
    html = re.sub(r"(©|&copy;)\s*(YEAR|20\d\d)", lambda m: f"{m.group(1)} {dt.date.today().year}", html)
    css_extra = []
    css = " ".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I))
    if not re.search(r"(^|[\s,}])img\s*\{[^}]*max-width\s*:\s*100%", css):
        css_extra.append("img{max-width:100%;height:auto}")
    m = re.search(r'aria-controls="([^"]+)"', html)
    if m and f'id="{m.group(1)}"' in html and "zoha-nav-guard" not in html and "data-bs-toggle" not in html:
        mid = m.group(1)
        css_extra.append(
            f"/* zoha-nav-guard: menu links on desktop, hamburger + closed menu on phones */"
            f"@media (min-width:761px){{[aria-controls=\"{mid}\"]{{display:none!important}}"
            f"#{mid}{{display:flex!important;position:static!important;flex-direction:row!important;box-shadow:none!important;padding:0!important;background:none!important}}}}"
            f"@media (max-width:760px){{[aria-controls=\"{mid}\"]{{display:inline-flex!important;min-height:44px;min-width:44px;align-items:center;justify-content:center}}"
            f"#{mid}:not(.open){{display:none!important}}#{mid} a{{min-height:44px;display:flex;align-items:center}}}}")
    if css_extra and "</style>" in html:
        i = html.lower().rfind("</style>")
        html = html[:i] + "\n    " + "\n    ".join(css_extra) + "\n  " + html[i:]
    return html


PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
PHOTO_HINTS = {   # words in a photo's file name → words in the slot label they suit
    "hero": ["slide one", "signature", "hero", "highlight"], "store": ["showroom", "space", "branch"],
    "front": ["branch", "showroom", "space"], "shop": ["showroom", "branch", "space"], "interior": ["showroom", "space", "our space"],
    "team": ["team", "people"], "staff": ["team"], "owner": ["proprietor", "portrait", "founder"], "founder": ["proprietor", "portrait"],
    "director": ["proprietor", "portrait"], "product": ["product", "offering", "category"], "cat": ["category", "offering"],
}


def place_photos(html: str, page_path: Path, folder: str) -> tuple:
    """Put the client's real photos into the page's photo slots (.photo / .art), copying them next to the page.
    Returns (html, how many placed). Photos are matched to slots by file-name hints, the rest in order."""
    src = Path(folder).expanduser()
    if not src.is_dir():
        return html, 0
    photos = sorted([p for p in src.iterdir() if p.suffix.lower() in PHOTO_EXT], key=lambda p: p.name.lower())
    if not photos:
        return html, 0
    assets = page_path.parent / f"{page_path.stem}_photos"
    assets.mkdir(exist_ok=True)
    slots = list(re.finditer(r'<div class="(photo|art[^"]*)"([^>]*)>(.*?)</div>', html, re.S))
    slots = [m for m in slots if "<img" not in m.group(3)]
    used, plan = set(), {}
    for m in slots:   # first pass: name hints
        label = (re.search(r'data-label="([^"]*)"', m.group(2)) or re.search(r"<span>([^<]*)</span>", m.group(3)) or [None, ""])[1].lower()
        for ph in photos:
            if ph in used:
                continue
            words = [w for k, ws in PHOTO_HINTS.items() if k in ph.stem.lower() for w in ws]
            if any(w in label for w in words):
                plan[m.start()] = (m, ph, label)
                used.add(ph)
                break
    rest = [ph for ph in photos if ph not in used]
    for m in slots:   # second pass: everything else in order
        if m.start() not in plan and rest:
            label = (re.search(r'data-label="([^"]*)"', m.group(2)) or [None, ""])[1]
            plan[m.start()] = (m, rest.pop(0), label)
    out, last = [], 0
    for start in sorted(plan):
        m, ph, label = plan[start]
        dest = assets / ph.name
        if not dest.exists():
            dest.write_bytes(ph.read_bytes())
        alt = re.sub(r"[_-]+", " ", ph.stem).strip().capitalize()
        lazy = "" if start == min(plan) else ' loading="lazy"'
        img = f'<img src="{assets.name}/{ph.name}" alt="{alt}"{lazy}>'
        out.append(html[last:m.start()] + f'<div class="{m.group(1)}"{m.group(2)}>{img}{m.group(3)}</div>')
        last = m.end()
    out.append(html[last:])
    return "".join(out), len(plan)


def strip_layers(html: str) -> str:
    """Remove the parts autofix_html adds (motion, 3D, nav guard, phone bar, favicon…) so a model only ever reads and
    writes the page itself – shorter prompts, and autofix puts fresh versions back afterwards."""
    i = html.lower().find("</style>")
    if i > 0:
        marks = [html.find(m, 0, i) for m in ("/* zoha-motion", "/* zoha-nav-guard", "/* zoha-3d", ".skip-link {")]
        marks = [m for m in marks if m > 0]
        if marks:
            html = html[:min(marks)].rstrip() + "\n  " + html[i:]
    html = re.sub(r'\s*<link rel="icon" href="data:image/svg\+xml[^"]*">', "", html)
    html = re.sub(r'\s*<meta name="theme-color"[^>]*>', "", html)
    html = re.sub(r'\s*<a class="skip-link"[^>]*>[^<]*</a>', "", html)
    html = re.sub(r'\s*<div class="m-bar">.*?</div>', "", html, flags=re.S)
    html = re.sub(r"\s*<script>/\* zoha-motion \*/.*?</script>", "", html, flags=re.S)
    html = re.sub(r'\s*<script type="importmap">.*?</script>', "", html, flags=re.S)
    html = re.sub(r'\s*<script type="module">/\* zoha-3d \*/.*?</script>', "", html, flags=re.S)
    return html


def final_cleanup(html: str) -> str:
    """Last resort after the fix passes: remove starter example text the model left behind and make facts agree,
    so a page never ships with 'Offer line for…' or 'since 2018 · 12 yrs'."""
    if "<html" not in html.lower():
        return html
    html = re.sub(r'\s*<div class="offer-bar">[^<]*(?:Offer line for|e\.g\.)[^<]*</div>', "", html)
    html = re.sub(r'\s*<p class="lead">\s*(?:One line about[^<]*|Who runs it[^<]*|One line with the offer[^<]*|'
                  r'Two sentences of real[^<]*|Landmark-style directions[^<]*)</p>', "", html)
    html = re.sub(r"<p>\s*One line with the offer or the next step\.\s*</p>", "", html)
    html = re.sub(r'A clear closing line, e\.g\. "([^"]+)"', r"\1", html)
    html = re.sub(r"(<strong>)\s*Fact about them\s*(</strong>)", r"\1Trusted locally\2", html)
    since = re.search(r"\bsince\s+((?:19|20)\d\d)\b", html, re.I)
    if since:
        n = dt.date.today().year - int(since.group(1))
        if n > 0:
            html = re.sub(r"(>\s*)(\d{1,3})(\+?\s*(?:yrs|years)\b)",
                          lambda m: m.group(1) + (str(n) if abs(int(m.group(2)) - n) > 1 else m.group(2)) + m.group(3), html, flags=re.I)
    return html


def _write(prompt: str, think: bool = False, temperature: float = 0.4) -> str:
    try:
        return CTX.writer(prompt, think=think, temperature=temperature)
    except TypeError:          # writer without these options (tests, other brains)
        try:
            return CTX.writer(prompt, think=think)
        except TypeError:
            return CTX.writer(prompt)


def score_page(path: Path, html: str) -> tuple:
    """Lower is better: code-check problems + real-browser problems (counted double)."""
    lint = lint_html(html)
    try:
        from .page_check import check_page
        path.write_text(html, encoding="utf-8")
        browser = check_page(path, None)
    except Exception:
        browser = []
    return len(lint) + 2 * len(browser) + (0 if "</html>" in html.lower() else 50), lint, browser


def _best_of(prompt: str, path: Path, n: int) -> str:
    """Best-of-N with execution feedback: write N drafts (different temperatures), test each in the
    checker + a real browser, keep the one with the fewest problems. Small models + this kind of
    selection beat bigger models on code benchmarks (e.g. S*, AlphaCode-style filtering)."""
    temps = [0.4, 0.75, 0.95, 0.6, 0.85][:max(1, n)]
    best, best_score = "", None
    for i, t in enumerate(temps):
        think = i == 0 and os.getenv("WRITE_MODE", "starter").lower() != "short"   # trained pages were written without thinking
        draft = _clean_writer(_write(prompt, think=think, temperature=t) or "")
        if len(draft) < 200:
            continue
        sc, lint_p, browser_p = score_page(path, draft)
        log.info("write_file draft %d/%d (temp %.2f): score %d %s", i + 1, len(temps), t, sc,
                 ("– " + " | ".join(x[:70] for x in (browser_p + lint_p)[:3])) if sc else "")
        if best_score is None or sc < best_score:
            best, best_score = draft, sc
        if sc == 0:
            break   # already clean – don't waste time
    return best


def _browser_fix(path: Path, name: str, text: str) -> tuple:
    """Open the page in a hidden browser (desktop + phone, plus Zoha's eyes), feed real problems back once."""
    try:
        from .page_check import check_page
    except Exception:
        return text, []
    problems = check_page(path, CTX.vision)
    if not problems:
        return text, []
    fixed = _clean_writer(_write(
        f"Here is {name}. I opened it in a real browser and found these problems:\n- " + "\n- ".join(problems)
        + f"\n\n{text}\n\nFix EXACTLY these problems and change nothing else. "
          "Output ONLY the complete corrected file – no notes, no fences.") or "")
    if len(fixed) < len(text) * 0.7 or "</html>" not in fixed.lower() or len(lint_html(fixed)) > len(lint_html(text)):
        return text, problems
    path.write_text(fixed, encoding="utf-8")
    left = check_page(path, None)          # re-test (no vision the second time – faster)
    if len(left) > len([p for p in problems if not p.startswith("Visual problem")]):
        path.write_text(text, encoding="utf-8")   # the "fix" made it worse – keep the earlier version
        return text, problems
    return fixed, left


def _fix_html(name: str, text: str, rounds: int = 2) -> str:
    for _ in range(rounds):
        problems = lint_html(text)
        if not problems:
            break
        fixed = _clean_writer(_write(
            f"Here is {name}.\n\n{text}\n\nFix EXACTLY these problems and change nothing else:\n- "
            + "\n- ".join(problems) + "\n\nOutput ONLY the complete corrected file – no notes, no fences.") or "")
        if len(fixed) > len(text) * 0.7 and "</html>" in fixed.lower() and len(lint_html(fixed)) < len(problems):
            text = fixed
        else:
            break
    return text


SKILL_ROUTES = [   # (skill file, words in the request) – checked in order, only for non-web, non-code files
    ("proposal", r"proposal|quotation|quote for|estimate|pitch|scope of work|invoice"),
    ("email", r"\bemail\b|\bmail\b|reply to|follow.?up"),
    ("social", r"instagram|caption|reel|post for|linkedin|tweet|hashtag|social media"),
    ("blog", r"\bblog\b|article|\.md\b|newsletter"),
]


def _skill_for(kind: str, request: str) -> str:
    if kind != "writing":
        return kind
    t = (request or "").lower()
    for name, rx in SKILL_ROUTES:
        if re.search(rx, t) and (SKILLS_DIR / f"{name}.md").exists():
            return name
    return kind


def _clean_writer(text: str) -> str:
    m = re.search(r"```[\w+-]*\n(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    text = autofix_html(text.strip()) if "<html" in text.lower() else text.strip()
    return text + "\n" if text else ""


@tool("write_file", "Write code, a letter, a document, notes or any longer text into a NEW file and open it "
      "(Notepad or the default app). Describe WHAT to write – the content is written separately, so never put "
      "the content itself here. Use this whenever the user asks to write code/a page/a letter in Notepad or a file.",
      "Write file", "📝",
      filename=("string", "File name with extension, e.g. 'boutique_landing.html', 'letter.txt'", True),
      what=("string", "What to write, with every detail the user gave (topic, style, sections, language)", True),
      folder=("string", "desktop (default), documents or downloads", False),
      open_with=("string", "notepad (default) or default (the file's usual app, e.g. a browser for .html)", False),
      photos=("string", "Web pages only: a folder with the client's real photos to place in the page", False),
      template=("string", "Web pages only: a template name from Zoha's library (agency, creative, grayscale, landing-page, "
                "business-casual, modern-business, …), 'auto' to pick one, or 'none' for Zoha's own designs", False))
def write_file(filename: str, what: str, folder: str = "desktop", open_with: str = "notepad", photos: str = "",
               template: str = "") -> str:
    if not CTX.writer:
        return "Error: writing files isn't available with the current brain."
    name = re.sub(r'[<>:"/\\|?*]+', "_", filename).strip() or "zoha_note.txt"
    if "." not in name:
        name += ".txt"
    base = Path.home() / KNOWN.get((folder or "desktop").lower(), "Desktop")
    path = base / name
    i = 2
    while path.exists():                         # never overwrite the user's files
        path = base / f"{Path(name).stem} ({i}){Path(name).suffix}"
        i += 1
    ext = path.suffix.lower().lstrip(".")
    web = ext in ("html", "htm")
    kind, fb = ("web-page", WEB_BRIEF) if web else (("code", CODE_BRIEF) if ext in CODE_EXT else ("writing", TEXT_BRIEF))
    kind = _skill_for(kind, f"{what} {name}")
    brief, checklist = _skill(kind, fb)
    prompt = (f"Write the complete content of a file named {name}.\nRequest: {what}\n\n{brief}\n\n"
              "Output ONLY the file content – no explanation before or after, no markdown fences.")
    starter = SKILLS_DIR / "web-starter.html"
    short = SKILLS_DIR / "web-short-prompt.txt"
    tmeta = None
    if web and (template or "").lower() not in ("none", "no", "own"):
        try:   # professional templates from the library (Start Bootstrap, MIT) – when asked, or now and then
            from . import templates_lib as TL
            ask = f"{template} {what}"
            if (template and template.lower() != "auto") or re.search(r"template|bootstrap|professional", ask.lower()) \
                    or template.lower() == "auto" or random.random() < 0.3:
                tmeta = TL.pick(template if template and template.lower() != "auto" else what) or \
                    (TL.pick(ask) if re.search(r"template|bootstrap", ask.lower()) else None)
        except Exception as e:
            log.info("template library unavailable: %s", e)
    if tmeta:
        base.mkdir(parents=True, exist_ok=True)
        thtml = TL.prepare(tmeta, path)
        prompt = TL.prompt_for(tmeta, name, what, thtml, dt.date.today().year)
        log.info("write_file template: %s", tmeta["id"])
    elif web and os.getenv("WRITE_MODE", "starter").lower() == "short" and short.exists():
        # after the web training round: the model learned the standard, so the short prompt is enough (faster)
        prompt = short.read_text(encoding="utf-8").replace("{name}", name).replace("{what}", what) \
            .replace("{year}", str(dt.date.today().year))
    elif web:   # small models edit a correct page far better than they invent one
        try:   # a different pre-tested design for every request (layout, palette, fonts)
            from .web_kit import build_starter
            start_html, design = build_starter(f"{what} {name}")
        except Exception:
            start_html, design = (starter.read_text(encoding="utf-8") if starter.exists() else ""), "standard"
        log.info("write_file design: %s", design)
        prompt = (f"Make the web page {name}. Request: {what}\n\n{brief}\n\n"
                  f"START FROM THIS STARTER FILE ({design}). It was designed for this business and already has a correct "
                  "nav (links on desktop, hamburger on phones), form, WhatsApp button, SEO tags and responsive CSS. KEEP ITS "
                  "LAYOUT, class names, colours, fonts and scripts – don't swap in a different or generic layout. Replace "
                  "EVERY placeholder (BUSINESS, AREA, YEAR, 'Specific promise…', 'Offering name', 'Fact about them', "
                  "'Short, believable review', '…', XXX numbers where you can) with real, specific content for this "
                  "business. Repeat the commented items to the count shown (e.g. 3–4 offerings, 6–8 menu rows, 3 reviews) "
                  "with ₹ prices. Keep every nav link's #id matching a section id. Remove the HTML comments."
                  "\n\nSTARTER:\n" + start_html
                  + "\n\nOutput ONLY the complete finished file – no explanation, no markdown fences.")
    try:
        if web:
            base.mkdir(parents=True, exist_ok=True)
            text = _best_of(prompt, path, 1 if tmeta else int(os.getenv("WRITE_SAMPLES", "3") or 3))
        else:
            text = _clean_writer(_write(prompt, think=True) or "")
        if len(text) < 20:
            return "Error: the writer came back empty – try again."
        if web:   # exact problems found by code → a targeted fix pass (small models fix named problems well)
            text = _fix_html(name, text)
            base.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            text, tested = _browser_fix(path, name, text)
            cleaned = final_cleanup(text)
            if cleaned != text:
                text = cleaned
                path.write_text(text, encoding="utf-8")
        elif ext in CODE_EXT:   # second pass against the checklist
            fixed = _clean_writer(CTX.writer(
                f"Here is a draft of {name} (request: {what}).\n\n{text}\n\nFix every item that fails this "
                f"checklist:\n{checklist}\n\nOutput ONLY the complete corrected file – no notes, no fences.") or "")
            if len(fixed) > len(text) * 0.6:
                text = fixed
    except Exception as e:
        return f"Error: couldn't write it ({type(e).__name__})."
    base.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if WIN:
        if (open_with or "notepad").lower().startswith("note"):
            subprocess.Popen(["notepad.exe", str(path)], creationflags=NO_WINDOW)
        else:
            os.startfile(str(path))
    lines = text.count("\n")
    CTX.last_file = path
    note = ""
    if web:
        note = (" I tested it in a browser on desktop and phone – no problems found." if not tested
                else f" I tested it in a browser and fixed what I could; still open: {tested[0][:120]}")
    if tmeta:
        note += f" Built on the '{tmeta.get('name')}' template ({tmeta.get('credit') or tmeta.get('license')}); its files are in {path.stem}_files."
    if web and photos:
        text2, n_ph = place_photos(text, path, photos)
        if n_ph:
            text = text2
            path.write_text(text, encoding="utf-8")
            note += f" Placed {n_ph} of your photos (copied into {path.stem}_photos next to the page)."
        else:
            note += " I couldn't find photos in that folder."
    if web and re.search(r"X{4}|98XXX", text):
        note += (" The phone/WhatsApp numbers are placeholders – tell me the real number (and address) and I'll put them in.")
    return f"Saved {path.name} in {base.name} ({lines} lines) and opened it.{note}"


@tool("improve_file", "Improve/redesign a file Zoha (or the user) already wrote – 'make the website better', 'the design looks "
      "basic', 'make the hero bolder', 'fix the mobile menu'. Leave filename out to improve the page Zoha made last. Saves a new "
      "version next to the original and opens it.",
      "Improve file", "✨",
      filename=("string", "File name (spoken is fine: 'gym underscore website'), a path, or leave out for the last page Zoha made", False),
      how=("string", "What to improve, in the user's words (empty = general polish)", False))
def improve_file(filename: str = "", how: str = "") -> str:
    if not CTX.writer:
        return "Error: improving files isn't available with the current brain."
    p = None
    if filename and filename.strip().lower() not in ("it", "that", "this", "last", "the page", "the website", "the site", "the file"):
        p = find_named(filename)
    if p is None and CTX.last_file and Path(CTX.last_file).exists() and (not filename or filename.strip().lower() in
                                                                          ("it", "that", "this", "last", "the page", "the website", "the site", "the file")):
        p = Path(CTX.last_file)
    if p is None and CTX.last_file and Path(CTX.last_file).exists() and filename:
        # a mis-heard name ("jim website") that matches nothing – the page Zoha just made is almost always what's meant
        last = Path(CTX.last_file)
        if Path(spoken_name(filename)).suffix.lower() in ("", last.suffix.lower()):
            p = last
    if p is None:
        return (f"Error: couldn't find {filename or 'a recent page'} on the Desktop, Documents or Downloads. "
                "Ask the user for the name, or list the Desktop with find_files (no query) so they can pick a number.")
    old = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() in (".html", ".htm"):
        old = strip_layers(old)   # the model edits the page itself; motion/3D/guards are re-added afterwards
    ext = p.suffix.lower().lstrip(".")
    web = ext in ("html", "htm")
    kind, fb = ("web-page", WEB_BRIEF) if web else (("code", CODE_BRIEF) if ext in CODE_EXT else ("writing", TEXT_BRIEF))
    kind = _skill_for(kind, f"{how} {p.name}")
    brief, _ = _skill(kind, fb)
    problems = lint_html(old) if web else []
    ask = (how or "").strip() or "Make it clearly better: stronger, more specific copy, better visual hierarchy and polish."
    prompt = (f"Here is {p.name}.\n\n{old}\n\nImprove it. The user wants: {ask}\n"
              + ("Also fix these problems:\n- " + "\n- ".join(problems) + "\n" if problems else "")
              + f"\nFollow these standards:\n{brief}\n\nOutput ONLY the complete improved file – no notes, no fences.")
    try:
        new = _clean_writer(_write(prompt, think=True) or "")
    except Exception as e:
        return f"Error: couldn't improve it ({type(e).__name__})."
    if len(new) < len(old) * 0.5 or (web and "</html>" not in new.lower()):
        return "Error: the improved version came out incomplete, so I kept the original. Try again."
    if web:
        try:
            new = _fix_html(p.name, new)
        except Exception:
            pass
    stem = re.sub(r"_v\d+$", "", p.stem)
    n = 2
    while (p.parent / f"{stem}_v{n}{p.suffix}").exists():
        n += 1
    out = p.parent / f"{stem}_v{n}{p.suffix}"
    out.write_text(new, encoding="utf-8")
    CTX.last_file = out
    if web:
        new, _ = _browser_fix(out, out.name, new)
        new = final_cleanup(new)
        out.write_text(new, encoding="utf-8")
    if WIN:
        subprocess.Popen(["notepad.exe", str(out)], creationflags=NO_WINDOW)
    left = len(lint_html(new)) if web else 0
    return (f"Saved the improved version as {out.name} (the original is untouched) and opened it."
            + (f" Fixed {len(problems) - left} of {len(problems)} issues I found." if problems else ""))


def _send_unicode(text: str):
    from ctypes import wintypes

    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", PUL)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", PUL)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    send = ctypes.windll.user32.SendInput
    for ch in text:
        if ch == "\n":
            _send_vk(0x0D)
            continue
        units = [int.from_bytes(ch.encode("utf-16-le")[i:i + 2], "little") for i in range(0, len(ch.encode("utf-16-le")), 2)]
        for u in units:
            for flags in (0x0004, 0x0004 | 0x0002):  # KEYEVENTF_UNICODE, + KEYUP
                inp = INPUT(type=1, u=_U(ki=KEYBDINPUT(0, u, flags, 0, None)))
                send(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.004)


@tool("clipboard", "Read the clipboard, or copy given text to it. Only write when you know the exact text; if the user names "
      "something you don't have (e.g. 'my email address'), ask for it instead of reading.", "Clipboard", "📋",
      action=("string", "read or write", True, ["read", "write"]), text=("string", "Text to copy (for write)", False))
def clipboard(action: str, text: str = "") -> str:
    if not WIN:
        return "Error: clipboard is Windows-only."
    if action == "write":
        _ps("Set-Clipboard -Value $env:ZOHA_CLIP", env={"ZOHA_CLIP": text})
        return "Copied to clipboard."
    content = _ps("Get-Clipboard -Raw")
    return f"Clipboard contains: {content[:3000]}" if content else "The clipboard is empty."


# ──────────────────────────────────────────────────────────────────────────────
# Timers, reminders, memory
# ──────────────────────────────────────────────────────────────────────────────
@tool("set_timer", "Start a countdown timer.", "Timer", "⏱",
      minutes=("number", "Minutes (can be fractional)", False), seconds=("number", "Extra seconds", False),
      label=("string", "What it's for (optional)", False))
def set_timer(minutes: float = 0, seconds: float = 0, label: str = "") -> str:
    total = float(minutes or 0) * 60 + float(seconds or 0)
    if total <= 0:
        return "Error: timer length must be positive."
    return CTX.schedule(total, label or _fmt_dur(total), "timer")


def resolve_clock(text: str, now: Optional[dt.datetime] = None) -> Optional[dt.datetime]:
    """'17:30', '5:30 pm', '5.30', '530', '5 pm', 'noon' → the next moment that time happens.
    Without am/pm, a 1-12 hour means whichever of the two (a.m./p.m.) comes first."""
    now = now or dt.datetime.now()
    s = str(text).lower().replace(".", ":").replace(" ", "")
    s = s.replace("a:m:", "am").replace("p:m:", "pm").rstrip(":")
    if s in ("noon", "midday"):
        s = "12:00pm"
    if s == "midnight":
        s = "12:00am"
    m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?(am|pm)?", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if h > 23 or mi > 59 or (ap and not 1 <= h <= 12):
        return None
    if ap:
        h = (h % 12) + (12 if ap == "pm" else 0)
        cands = [h]
    elif 1 <= h <= 12 and not str(text).strip().startswith("0"):
        cands = [h % 12, h % 12 + 12]
    else:
        cands = [h]
    best = None
    for hh in cands:
        t = now.replace(hour=hh, minute=mi, second=0, microsecond=0)
        if t <= now:
            t += dt.timedelta(days=1)
        best = t if best is None or t < best else best
    return best


@tool("set_reminder", "Remind the user of something at a clock time today/tomorrow, or after a delay.", "Reminder", "🔔",
      message=("string", "What to remind about", True),
      at_time=("string", "Clock time, e.g. 17:30 or 5:30 pm (optional)", False),
      in_minutes=("number", "Or: minutes from now (optional)", False))
def set_reminder(message: str, at_time: Optional[str] = None, in_minutes: Optional[float] = None) -> str:
    if at_time:
        target = resolve_clock(at_time)
        if not target:
            return f"Error: I couldn't read '{at_time}' as a time. Use something like 17:30 or 5:30 pm."
        delay = (target - dt.datetime.now()).total_seconds()
    elif in_minutes:
        delay = float(in_minutes) * 60
    else:
        return "Error: give at_time or in_minutes."
    return CTX.schedule(delay, message, "reminder")


@tool("list_timers", "List active timers and reminders.", "Timers", "⏱")
def list_timers() -> str:
    return CTX.list_timers()


@tool("cancel_timer", "Cancel a timer/reminder (by label words, or 'all').", "Cancel timer", "⏹",
      which=("string", "Label text or 'all'", True))
def cancel_timer(which: str) -> str:
    return CTX.cancel_timer(which)


@tool("remember", "Store a long-term fact/preference ONLY when the user explicitly asks you to remember it ('remember that…'). "
      "Never for commands like 'be quiet', 'stop', 'wait'.", "Remembered", "🧠",
      fact=("string", "The fact, phrased in third person, e.g. 'the user's sister is Riya'", True))
def remember(fact: str) -> str:
    return CTX.memory.remember(fact) if CTX.memory else "Memory unavailable."


@tool("forget", "Delete stored facts when the user asks to forget, delete, remove or erase a memory (e.g. 'delete the memory about "
      "coffee' → about='coffee'). Never call remember for these.", "Forgot", "🧽",
      about=("string", "Words identifying the fact", True))
def forget(about: str) -> str:
    return CTX.memory.forget(about) if CTX.memory else "Memory unavailable."


def _fmt_dur(sec: float) -> str:
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    out = []
    if h:
        out.append(f"{h} hour{'s' * (h != 1)}")
    if m:
        out.append(f"{m} minute{'s' * (m != 1)}")
    if s and not h:
        out.append(f"{s} second{'s' * (s != 1)}")
    return " ".join(out) or "0 seconds"


def schemas() -> List[Dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in REGISTRY.values()]


# ──────────────────────────────────────────────────────────────────────────────
# Zoha's own browser (Playwright) – for doing things ON websites
# ──────────────────────────────────────────────────────────────────────────────
def _br():
    try:
        import playwright  # noqa: F401
    except ImportError:
        raise RuntimeError("Playwright isn't installed, so I can't use my own browser yet. Run: pip install playwright")
    from .browser import get_browser

    return get_browser()


@tool("browser_open", "Open a URL or search query in YOUR OWN controllable browser window (use this, not open_website, when you need to "
      "read or operate the page: fill forms, click, log in, compare, check something on a site). Returns the page's "
      "numbered interactive elements and visible text.", "Opening page", "🧭",
      target=("string", "URL, domain, or a search query", True),
      new_tab=("boolean", "Open in a new tab", False),
      open_result=("integer", "For a search: then open this result straight away (1 = first result, ads skipped)", False))
def browser_open(target: str, new_tab: bool = False, open_result: Optional[int] = None) -> str:
    res = _br().open(target, bool(new_tab))
    if open_result and not res.lower().startswith("error"):
        return _br().open_result(int(open_result))
    return res


@tool("browser_read", "Re-read the current page in your browser: numbered elements + visible text. Use full=true for long articles.",
      "Reading page", "📖", full=("boolean", "Return much more text", False))
def browser_read(full: bool = False) -> str:
    return _br().read(bool(full))


@tool("browser_click", "Click an element in your browser by its [ref] number from the latest snapshot (or by visible text). "
      "Irreversible actions (pay, buy, send, post, delete, submit) need confirmed=true AFTER the user says yes.",
      "Clicking", "👆", ref=("integer", "Element number from the snapshot", False),
      text=("string", "Visible text of the element if no ref", False),
      confirmed=("boolean", "User explicitly confirmed this irreversible click", False),
      result=("integer", "On a search results page: open the Nth result (1 = first, ads skipped) – use for 'open the first link'", False))
def browser_click(ref: Optional[int] = None, text: Optional[str] = None, confirmed: bool = False,
                  result: Optional[int] = None) -> str:
    if result:
        return _br().open_result(int(result))
    return _br().click(ref, text, bool(confirmed))


@tool("browser_type", "Type text into a field in your browser (by [ref] or by its label/placeholder). Never use for passwords.",
      "Typing", "⌨", text=("string", "Text to enter", True), ref=("integer", "Field number", False),
      field=("string", "Field label/placeholder if no ref", False),
      submit=("boolean", "Press Enter afterwards (e.g. search boxes)", False))
def browser_type(text: str, ref: Optional[int] = None, field: Optional[str] = None, submit: bool = False) -> str:
    return _br().type(text, ref, field, bool(submit))


@tool("browser_select", "Choose an option in a dropdown (select) in your browser.", "Choosing option", "☰",
      ref=("integer", "Dropdown number", True), option=("string", "Option label", True))
def browser_select(ref: int, option: str) -> str:
    return _br().select(int(ref), option)


@tool("browser_press", "Press a key in your browser, e.g. Enter, Escape, Tab, ArrowDown, PageDown, Control+F.", "Pressing key", "⏎",
      key=("string", "Key name", True))
def browser_press(key: str) -> str:
    return _br().press(key)


@tool("browser_scroll", "Scroll the page in your browser. To show a section ('the FAQ', 'team section', 'pricing') use to= with its name – "
      "it jumps straight there. Use pixels= for small exact moves.", "Scrolling", "↕",
      direction=("string", "Where to scroll", True, ["down", "up", "top", "bottom"]),
      pixels=("integer", "Scroll exactly this many pixels (e.g. 'scroll down 20 pixels')", False),
      to=("string", "Name of a section or heading to jump to, e.g. 'FAQ', 'team', 'pricing', 'contact'", False))
def browser_scroll(direction: str = "down", pixels: Optional[int] = None, to: Optional[str] = None) -> str:
    return _br().scroll(direction, pixels, to)


@tool("browser_nav", "Go back, forward or reload in your browser.", "Navigating", "↩",
      action=("string", "Navigation", True, ["back", "forward", "reload"]))
def browser_nav(action: str) -> str:
    return _br().nav(action)


@tool("browser_tabs", "List, switch, open or close tabs in your browser.", "Tabs", "🗂",
      action=("string", "Tab action", True, ["list", "switch", "new", "close"]),
      index=("integer", "Tab number (1-based) for switch/close", False))
def browser_tabs(action: str = "list", index: Optional[int] = None) -> str:
    return _br().tabs(action, index)


@tool("browser_video", "Control the video playing in YOUR browser (YouTube etc.): fullscreen, exit_fullscreen, play, pause, mute, unmute, "
      "forward/back N seconds, seek to second, restart from the beginning, captions_on/captions_off (subtitles/CC), speed, volume 0-100, next (YouTube), "
      "skip_ad, status. Use this instead of clicking player buttons. 'Go to 5 minutes' / 'jump to 10:30' = seek with value in seconds "
      "(300 / 630) – never a timer. 'Full screen' while a video is open = fullscreen here, not browser_window.",
      "Video", "🎬", action=("string", "What to do", True, ["fullscreen", "exit_fullscreen", "play", "pause", "mute", "unmute", "forward",
                                                         "back", "seek", "restart", "captions_on", "captions_off", "speed", "volume",
                                                         "next", "skip_ad", "skip", "status"]),
      seconds=("number", "Seconds for forward/back (default 10)", False),
      value=("number", "Target second for seek, rate for speed (e.g. 1.5), or 0-100 for volume", False))
def browser_video(action: str, seconds: float = 10, value: float = 0) -> str:
    return _br().video(action, float(seconds or 10), float(value or 0))


@tool("browser_window", "Resize YOUR browser WINDOW itself: maximize, minimize, restore, or window-fullscreen. NOT for videos – "
      "for 'full screen' / 'exit full screen' / 'small screen' while a video is open, use browser_video.", "Browser window", "🗖",
      state=("string", "Window state", True, ["maximize", "minimize", "fullscreen", "restore"]))
def browser_window(state: str) -> str:
    return _br().window(state)


@tool("browser_look", "LOOK at your browser page (screenshot with every clickable element numbered) and answer a question about it, "
      "e.g. 'which number is the Middle of the Night video?', 'where is the fullscreen button?', 'what does the page show?'. "
      "Use when the element list is ambiguous or you need to see the page.", "Looking at the page", "👁",
      question=("string", "What you need to know from the screenshot", True))
def browser_look(question: str) -> str:
    if CTX.vision is None:
        return "Error: the current brain can't see images – use browser_read instead."
    img, items = _br().look()
    prompt = ("This is a screenshot of a web page. Interactive elements are outlined in red with their [number] in the top-left "
              f"corner. {question}\nIf the answer is an element to click or type into, give its number like [12]. Be brief.")
    answer = CTX.vision(prompt, img)
    return f"Looking at the page: {answer.strip()}\n\n{items}"


@tool("browser_close", "Close your browser window when the task is finished and the user doesn't need it.", "Closing browser", "✖")
def browser_close() -> str:
    return _br().close()


# Optional website/CMS plugin (Agent API) – only when SITE_API_URL + SITE_API_KEY are set
try:
    from dotenv import load_dotenv as _ld
    _ld()
except Exception:
    pass
if os.getenv("SITE_API_URL") and os.getenv("SITE_API_KEY"):
    from . import site_plugin  # noqa: E402,F401

# Community plugins: every plugins/*.py next to main.py can add tools with @tool (see plugins/README.md)
from . import plugins as _plugins  # noqa: E402
_plugins.load_all()
