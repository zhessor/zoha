"""
Zoha's own browser (Playwright).

A real, visible Edge/Chrome window with its own persistent profile in data/browser-profile
(sign in once, stays signed in). Zoha operates it like a person: read the page →
see numbered interactive elements → click / type / scroll / switch tabs.

All Playwright calls run on ONE dedicated thread (Playwright's sync API is not
thread-safe); tools submit jobs to it and wait.
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
import os
import queue
import re
import sys
import threading
import time
import urllib.parse
from typing import Any, Callable, Optional

from .config import DATA_DIR

log = logging.getLogger("zoha.browser")

PROFILE = DATA_DIR / "browser-profile"

SNAPSHOT_JS = r"""
(maxItems) => {
  const sel = 'a[href],button,input:not([type=hidden]),textarea,select,summary,[role=button],[role=link],[role=tab],' +
              '[role=menuitem],[role=checkbox],[role=radio],[role=option],[role=switch],[role=combobox],[role=searchbox],' +
              '[role=textbox],[contenteditable=""],[contenteditable=true],[onclick],[tabindex]:not([tabindex="-1"])';
  document.querySelectorAll('[data-zoha-ref]').forEach(e => e.removeAttribute('data-zoha-ref'));
  const vh = window.innerHeight;
  const clean = t => (t || '').trim().replace(/\s+/g, ' ');
  const weak = t => !t || /^[\d:\s.,|•·-]+$/.test(t) || t.length < 2;       // "3:04", "1.2M", "" …
  const cands = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') continue;
    if (r.bottom < -vh || r.top > vh * 2.5) continue;
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role');
    const type = (el.getAttribute('type') || '').toLowerCase();
    let name = clean(el.getAttribute('aria-label') || el.getAttribute('title'));
    const inner = clean(el.innerText);
    if (weak(name)) name = inner && !weak(inner) ? inner : name;
    if (weak(name)) name = clean(el.value || el.getAttribute('placeholder') || el.getAttribute('alt') || el.getAttribute('name')) || name;
    if (weak(name)) { const img = el.querySelector('img[alt],[aria-label],[title]');
      if (img) name = clean(img.getAttribute('alt') || img.getAttribute('aria-label') || img.getAttribute('title')) || name; }
    const href = tag === 'a' ? (el.getAttribute('href') || '') : '';
    if (weak(name) && href) name = (inner ? inner + ' ' : '') + '→ ' + href.slice(0, 60);
    cands.push({el, tag, role, type, name: name.slice(0, 100), href, r, score: weak(name) ? 0 : name.length});
  }
  // the same link often appears 2-3 times (thumbnail, duration badge, title) → keep the best-named one
  const best = new Map();
  for (const c of cands) {
    if (!c.href) continue;
    const k = c.href.split('&')[0];
    if (!best.has(k) || best.get(k).score < c.score) best.set(k, c);
  }
  const out = []; let n = 0;
  for (const c of cands) {
    if (c.href && best.get(c.href.split('&')[0]) !== c) continue;
    n++; c.el.setAttribute('data-zoha-ref', String(n));
    const {el, tag, role, type} = c;
    let kind = role || (tag === 'input' ? (type || 'text') + ' field' : tag === 'a' ? 'link' : tag);
    if (tag === 'textarea') kind = 'text area';
    if (c.href && /\/watch\?v=|youtu\.be\//.test(c.href)) kind = 'video link';
    let extra = '';
    if (tag === 'input' && ['checkbox','radio'].includes(type)) extra = el.checked ? ' [checked]' : ' [unchecked]';
    else if ((tag === 'input' || tag === 'textarea') && el.value && type !== 'password') extra = ' value="' + el.value.slice(0, 40) + '"';
    if (type === 'password') extra = ' (PASSWORD – never fill)';
    if (el.disabled) extra += ' [disabled]';
    const where = c.r.top > vh ? ' ↓' : (c.r.bottom < 0 ? ' ↑' : '');
    out.push('[' + n + '] ' + kind + ' "' + c.name + '"' + extra + where);
    if (n >= maxItems) break;
  }
  const v = document.querySelector('video');
  if (v && v.duration) out.unshift('(page has a video: ' + (v.paused ? 'paused' : 'playing') + ' at ' +
      Math.floor(v.currentTime) + 's of ' + Math.floor(v.duration) + 's – use browser_video to control it)');
  return out;
}
"""

SCROLL_TO_JS = r"""
(want) => {
  let w = want.toLowerCase().replace(/\b(the|section|part|area|page)\b/g, '').trim() || want.toLowerCase();
  const alias = {"faq": "frequently asked", "faqs": "frequently asked", "about us": "about", "team members": "team"};
  const words = [w].concat(alias[w] ? [alias[w]] : []);
  const norm = (t) => (t || '').toLowerCase().replace(/\s+/g, ' ').trim();
  const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const tiers = [
    () => Array.from(document.querySelectorAll('h1,h2,h3,h4,[role=heading]')).filter(e => norm(e.innerText) === w),
    () => Array.from(document.querySelectorAll('h1,h2,h3,h4,[role=heading]')).filter(e => norm(e.innerText).includes(w)),
    () => Array.from(document.querySelectorAll('section[id],div[id],[id]')).filter(e => norm(e.id).replace(/[-_]/g, ' ').includes(w)),
    () => Array.from(document.querySelectorAll('section,header,footer,div')).filter(e => norm(e.getAttribute('aria-label')).includes(w)),
    () => Array.from(document.querySelectorAll('p,span,a,button,li,dt,summary')).filter(e => norm(e.innerText).includes(w) && norm(e.innerText).length < 120),
  ];
  for (const ww of words) {
    w = ww;
    for (const t of tiers) {
      const hit = t().find(vis);
      if (hit) { hit.scrollIntoView({block: 'start', behavior: 'instant'}); window.scrollBy(0, -70);
                 return (hit.innerText || hit.id || want).trim().split('\n')[0].slice(0, 60); }
    }
  }
  return '';
}
"""

ON_SCREEN_JS = r"""
() => {
  const H = window.innerHeight, out = [];
  for (const e of document.querySelectorAll('h1,h2,h3,[role=heading]')) {
    const r = e.getBoundingClientRect();
    if (r.bottom > 0 && r.top < H && r.width > 0) { const t = (e.innerText || '').trim().replace(/\s+/g, ' '); if (t) out.push(t.slice(0, 70)); }
  }
  const pct = Math.round(100 * window.scrollY / Math.max(1, document.documentElement.scrollHeight - H));
  return {headings: out.slice(0, 8), pct: isFinite(pct) ? pct : 0};
}
"""

RESULTS_JS = r"""
() => {
  const host = location.hostname;
  const pick = (sel) => Array.from(document.querySelectorAll(sel));
  let links = [];
  if (/(^|\.)google\./.test(host)) links = pick('#search a h3, #rso a h3').map(h => h.closest('a'));
  else if (/bing\.com$/.test(host)) links = pick('#b_results li.b_algo h2 a');
  else if (/duckduckgo\.com$/.test(host)) links = pick('a[data-testid="result-title-a"], .result__a');
  const seen = new Set();
  return links
    .filter(a => a && a.href && /^https?:/.test(a.href) && !/google\.[a-z.]+\/(search|url|aclk)|googleadservices|bing\.com\/aclk/.test(a.href))
    .filter(a => !seen.has(a.href) && seen.add(a.href))
    .map(a => ({href: a.href, title: ((a.querySelector('h3') || a).innerText || '').trim().slice(0, 120)}));
}
"""

RISKY = re.compile(r"\b(pay|payment|buy|purchase|place order|checkout|confirm order|send|post|publish|tweet|reply|"
                   r"delete|remove|unsubscribe|transfer|donate|submit|book now|subscribe|sign out|log ?out)\b", re.I)


class BrowserError(Exception):
    pass


class Browser:
    def __init__(self, channel: str = "auto"):
        self.channel = channel
        self._q: "queue.Queue" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._pw = None
        self.ctx = None
        self.page = None
        self.used_channel = None

    # ── worker thread ────────────────────────────────────────────────
    def _run(self):
        while True:
            fn, fut = self._q.get()
            if fn is None:
                break
            if fut.set_running_or_notify_cancel():
                try:
                    fut.set_result(fn())
                except Exception as e:
                    fut.set_exception(e)
        self._close_all()

    def call(self, fn: Callable[[], Any], timeout: float = 90) -> Any:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True, name="zoha-browser")
            self._thread.start()
        fut: cf.Future = cf.Future()
        self._q.put((fn, fut))
        return fut.result(timeout=timeout)

    def shutdown(self):
        if self._thread and self._thread.is_alive():
            self._q.put((None, None))

    # ── lifecycle (browser thread only) ──────────────────────────────
    def _alive(self) -> bool:
        try:
            return self.ctx is not None and self.page is not None and not self.page.is_closed() and bool(self.ctx.pages)
        except Exception:
            return False

    def _ensure(self):
        if self._alive():
            return
        if self.ctx is not None:
            # user closed the window or a tab: adopt any open tab, else relaunch
            try:
                pages = [p for p in self.ctx.pages if not p.is_closed()]
                if pages:
                    self.page = pages[-1]
                    return
            except Exception:
                pass
            self._close_all()
        from playwright.sync_api import sync_playwright

        if self._pw is None:
            self._pw = sync_playwright().start()
        PROFILE.mkdir(parents=True, exist_ok=True)
        order = {"auto": ["msedge", "chrome", None], "msedge": ["msedge", None], "chrome": ["chrome", None],
                 "chromium": [None]}.get(self.channel, ["msedge", "chrome", None])
        last = None
        headless = os.getenv("ZOHA_BROWSER_HEADLESS", "") == "1"
        for ch in order:
            try:
                kw = dict(user_data_dir=str(PROFILE), headless=headless, no_viewport=True,
                          args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
                          ignore_default_args=["--enable-automation"])
                if ch:
                    kw["channel"] = ch
                self.ctx = self._pw.chromium.launch_persistent_context(**kw)
                self.used_channel = ch or "chromium"
                break
            except Exception as e:
                last = e
                log.info("Browser channel %s unavailable: %s", ch, str(e).splitlines()[0][:120])
        if self.ctx is None:
            raise BrowserError(f"Couldn't start a browser ({last}). Install Edge/Chrome or run: python -m playwright install chromium")
        self.ctx.set_default_timeout(10000)
        self.ctx.on("page", self._on_new_page)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        log.info("Browser started (%s)", self.used_channel)

    def _on_new_page(self, page):
        self.page = page  # follow links that open in a new tab

    def _close_all(self):
        for obj in (self.ctx,):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        self.ctx = self.page = None
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pw = None

    # ── helpers (browser thread) ─────────────────────────────────────
    def _settle(self, ms: int = 6000):
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=ms)
        except Exception:
            pass
        try:
            self.page.wait_for_load_state("networkidle", timeout=1800)
        except Exception:
            pass

    def _snapshot(self, max_items: int = 70, text_chars: int = 2500) -> str:
        p = self.page
        try:
            items = p.evaluate(SNAPSHOT_JS, max_items)
        except Exception as e:
            items = [f"(couldn't list elements: {e})"]
        try:
            text = p.evaluate("() => document.body ? document.body.innerText : ''") or ""
        except Exception:
            text = ""
        text = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()
        if len(text) > text_chars:
            text = text[:text_chars] + " …(more – use browser_read for full text)"
        try:
            n_tabs = len(self.ctx.pages)
        except Exception:
            n_tabs = 1
        try:
            title = p.title()
        except Exception:
            title = ""
        try:
            scr = p.evaluate(ON_SCREEN_JS) or {}
            on_screen = (f"On screen right now ({scr.get('pct', 0)}% down the page): "
                         + (" | ".join(scr.get("headings") or []) or "no headings visible"))
        except Exception:
            on_screen = ""
        return (f"Tab: {title} | {p.url} | {n_tabs} tab(s) open\n"
                + (on_screen + "\n" if on_screen else "") +
                f"Interactive elements (use the [number] as ref):\n" + "\n".join(items) +
                f"\n\nPage text (the WHOLE page – only the part under 'On screen right now' is visible to the user):\n{text}")

    def _loc(self, ref: Optional[int], text: Optional[str]):
        p = self.page
        if ref is not None:
            loc = p.locator(f'[data-zoha-ref="{int(ref)}"]')
            if loc.count() == 0:
                raise BrowserError(f"Element [{ref}] isn't on the page any more – call browser_read for fresh numbers.")
            return loc.first
        if text:
            for cand in (p.get_by_role("button", name=text), p.get_by_role("link", name=text),
                         p.get_by_label(text), p.get_by_placeholder(text), p.get_by_text(text, exact=False)):
                try:
                    if cand.count() > 0 and cand.first.is_visible():
                        return cand.first
                except Exception:
                    continue
            raise BrowserError(f"No element matching '{text}'.")
        raise BrowserError("Give a ref number (from browser_read) or the element's visible text.")

    def _describe(self, loc) -> str:
        try:
            return (loc.get_attribute("aria-label") or loc.inner_text(timeout=1500) or loc.get_attribute("value") or "").strip()[:120]
        except Exception:
            return ""

    # ── public actions (each runs on the browser thread) ─────────────
    def open(self, target: str, new_tab: bool = False) -> str:
        def job():
            self._ensure()
            t = target.strip()
            if re.match(r"^[a-z]+://", t, re.I):
                url = t
            elif re.match(r"^[\w-]+(\.[\w-]+)+(/.*)?$", t):
                url = "https://" + t
            else:
                url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(t)
            if new_tab:
                self.page = self.ctx.new_page()
            self.page.goto(url, wait_until="domcontentloaded", timeout=25000)
            self._settle()
            self.page.bring_to_front()
            return self._snapshot()

        return self.call(job)

    def read(self, full: bool = False) -> str:
        def job():
            self._ensure()
            return self._snapshot(max_items=120 if full else 70, text_chars=12000 if full else 2500)

        return self.call(job)

    def click(self, ref: Optional[int] = None, text: Optional[str] = None, confirmed: bool = False) -> str:
        def job():
            self._ensure()
            loc = self._loc(ref, text)
            label = self._describe(loc) or (text or "")
            if RISKY.search(label) and not confirmed:
                return (f"STOPPED: '{label}' looks like an irreversible action (pay/send/post/delete/submit). "
                        "Ask the user to confirm, then call again with confirmed=true.")
            before = len(self.ctx.pages)
            try:
                loc.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            loc.click(timeout=8000)
            # pump Playwright events briefly so a tab opened by this click is noticed
            for _ in range(8):
                self.page.wait_for_timeout(150)
                pages = [p for p in self.ctx.pages if not p.is_closed()]
                if len(pages) > before:
                    self.page = pages[-1]
                    self.page.bring_to_front()
                    break
            self._settle()
            return f"Clicked '{label}'.\n" + self._snapshot()

        return self.call(job)

    def type(self, text: str, ref: Optional[int] = None, field: Optional[str] = None, submit: bool = False) -> str:
        def job():
            self._ensure()
            loc = self._loc(ref, field)
            if (loc.get_attribute("type") or "").lower() == "password":
                return "STOPPED: that's a password field. Ask the user to type their password themselves."
            try:
                loc.fill(text, timeout=6000)
            except Exception:
                loc.click()
                self.page.keyboard.press("Control+A")
                self.page.keyboard.type(text, delay=15)
            if submit:
                loc.press("Enter")
                self._settle()
            return f"Typed into the field{' and pressed Enter' if submit else ''}.\n" + self._snapshot()

        return self.call(job)

    def press(self, key: str) -> str:
        def job():
            self._ensure()
            self.page.keyboard.press(key)
            self._settle(3000)
            return f"Pressed {key}.\n" + self._snapshot(text_chars=1200)

        return self.call(job)

    def select(self, ref: int, option: str) -> str:
        def job():
            self._ensure()
            loc = self._loc(ref, None)
            try:
                loc.select_option(label=option, timeout=5000)
            except Exception:
                loc.select_option(value=option, timeout=5000)
            return f"Selected '{option}'.\n" + self._snapshot(text_chars=800)

        return self.call(job)

    def scroll(self, direction: str = "down", pixels: Optional[int] = None, to: Optional[str] = None) -> str:
        def job():
            self._ensure()
            if to:
                found = self.page.evaluate(SCROLL_TO_JS, to)
                if not found:
                    return (f"Error: couldn't find a section called '{to}' on this page. "
                            "Read the page, or open the site's own page for it (e.g. /faq).\n" + self._snapshot())
                self.page.wait_for_timeout(600)
                return f"Scrolled to '{found}'.\n" + self._snapshot()
            if pixels:
                dy = abs(int(pixels)) * (-1 if direction == "up" else 1)
                self.page.evaluate(f"() => window.scrollBy(0, {dy})")
            elif direction == "top":
                self.page.evaluate("() => window.scrollTo(0, 0)")
            elif direction == "bottom":
                self.page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            else:
                dy = 0.8 if direction == "down" else -0.8
                self.page.evaluate(f"() => window.scrollBy(0, window.innerHeight * {dy})")
            self.page.wait_for_timeout(500)
            return f"Scrolled {direction}.\n" + self._snapshot()

        return self.call(job)

    def open_result(self, n: int = 1) -> str:
        """Open the Nth real result on a search results page (Google/Bing/DuckDuckGo), skipping ads."""
        def job():
            self._ensure()
            links = self.page.evaluate(RESULTS_JS) or []
            if not links:
                return ("Error: this page doesn't look like a list of search results, so there's no 'first result' to open. "
                        "Read the page and click the link you want instead.")
            i = max(1, int(n or 1))
            if i > len(links):
                return f"Error: there are only {len(links)} results on this page."
            href, title = links[i - 1]["href"], links[i - 1]["title"]
            self.page.goto(href, wait_until="domcontentloaded", timeout=25000)
            self._settle()
            return f"Opened result {i}: {title}\n" + self._snapshot()

        return self.call(job)

    def nav(self, action: str) -> str:
        def job():
            self._ensure()
            if action == "back":
                self.page.go_back(wait_until="domcontentloaded")
            elif action == "forward":
                self.page.go_forward(wait_until="domcontentloaded")
            elif action == "reload":
                self.page.reload(wait_until="domcontentloaded")
            self._settle()
            return f"Went {action}.\n" + self._snapshot()

        return self.call(job)

    def tabs(self, action: str = "list", index: Optional[int] = None) -> str:
        def job():
            self._ensure()
            pages = [p for p in self.ctx.pages if not p.is_closed()]
            if action == "switch" and index is not None:
                if not 1 <= index <= len(pages):
                    return f"Error: there are {len(pages)} tabs."
                self.page = pages[index - 1]
                self.page.bring_to_front()
                return f"Switched to tab {index}.\n" + self._snapshot()
            if action == "close":
                target = pages[index - 1] if index and 1 <= index <= len(pages) else self.page
                target.close()
                rest = [p for p in self.ctx.pages if not p.is_closed()]
                if not rest:
                    self.page = self.ctx.new_page()
                else:
                    self.page = rest[-1]
                return "Closed the tab."
            if action == "new":
                self.page = self.ctx.new_page()
                return "Opened a new tab."
            lines = []
            for i, p in enumerate(pages, 1):
                try:
                    t = p.title()
                except Exception:
                    t = ""
                lines.append(f"{i}. {t} — {p.url}{'  (current)' if p == self.page else ''}")
            return "Open tabs:\n" + "\n".join(lines)

        return self.call(job)

    def video(self, action: str, seconds: float = 10, value: float = 0) -> str:
        """Control the HTML5 video on the current page (YouTube and most sites)."""
        def job():
            self._ensure()
            p = self.page
            yt = "youtube.com" in p.url
            if p.evaluate("() => !document.querySelector('video')"):
                return "Error: there's no video on the current page."
            js = lambda code: p.evaluate("(a) => { const v = document.querySelector('video'); " + code + " }", [seconds, value])
            if action in ("fullscreen", "exit_fullscreen"):
                want = action == "fullscreen"
                is_fs = p.evaluate("() => !!document.fullscreenElement")
                if is_fs == want:
                    return f"The video is already {'in' if want else 'out of'} full screen."
                if want:
                    p.evaluate("() => document.activeElement && document.activeElement.blur && document.activeElement.blur()")
                    p.locator("video").first.hover(timeout=3000)
                    p.keyboard.press("f")  # YouTube / most players: real key press counts as a user gesture
                    p.wait_for_timeout(600)
                    if not p.evaluate("() => !!document.fullscreenElement"):
                        # generic players: request fullscreen flagged as a user gesture (DevTools protocol)
                        try:
                            cdp = self.ctx.new_cdp_session(p)
                            cdp.send("Runtime.evaluate", {
                                "expression": "(document.querySelector('.html5-video-player') || document.querySelector('video'))"
                                              ".requestFullscreen()",
                                "userGesture": True, "awaitPromise": True})
                            p.wait_for_timeout(500)
                        except Exception as e:
                            log.debug("CDP fullscreen failed: %s", e)
                    if not p.evaluate("() => !!document.fullscreenElement"):
                        p.locator("video").first.dblclick(timeout=3000)
                        p.wait_for_timeout(600)
                    ok = p.evaluate("() => !!document.fullscreenElement")
                    return "The video is now full screen." if ok else "Error: the page didn't allow full screen."
                p.keyboard.press("Escape")
                p.wait_for_timeout(300)
                if p.evaluate("() => !!document.fullscreenElement"):
                    p.evaluate("() => document.exitFullscreen()")
                    p.wait_for_timeout(300)
                ok = not p.evaluate("() => !!document.fullscreenElement")
                return "Exited full screen." if ok else "Error: couldn't leave full screen – press Esc."
            if action == "pause":
                js("v.pause();")
            elif action == "play":
                js("v.play();")
            elif action == "mute":
                js("v.muted = true;")
            elif action == "unmute":
                js("v.muted = false;")
            elif action == "forward":
                js("v.currentTime = Math.min(v.duration || 1e9, v.currentTime + a[0]);")
            elif action == "back":
                js("v.currentTime = Math.max(0, v.currentTime - a[0]);")
            elif action == "seek":
                js("v.currentTime = a[1];")
            elif action == "speed":
                js("v.playbackRate = a[1] || 1;")
            elif action == "volume":
                js("v.muted = false; v.volume = Math.max(0, Math.min(1, a[1] / 100));")
            elif action == "restart":
                js("v.currentTime = 0; v.play();")
            elif action in ("captions_on", "captions_off", "captions"):
                tracks_js = "() => { const v = document.querySelector('video'); return v ? [...v.textTracks].map(t => t.mode) : []; }"
                if yt:
                    btn = p.locator(".ytp-subtitles-button").first
                    if btn.count() == 0 or not btn.is_visible():
                        return "This video has no captions button."
                    if btn.get_attribute("aria-disabled") == "true" or (btn.get_attribute("title") or "").lower().startswith("subtitles/closed captions unavailable"):
                        return "This video has no captions."
                    on = btn.get_attribute("aria-pressed") == "true"
                    want = {"captions_on": True, "captions_off": False}.get(action, not on)
                    if on == want:
                        return f"Captions are already {'on' if want else 'off'}."
                    p.locator("video").first.hover(timeout=3000)
                    btn.click(timeout=3000)
                    p.wait_for_timeout(300)
                    now = btn.get_attribute("aria-pressed") == "true"
                    return f"Captions are now {'on' if now else 'off'}." if now == want else "Error: the captions button didn't respond."
                modes = p.evaluate(tracks_js)
                if not modes:
                    return "This video has no captions."
                on = any(m == "showing" for m in modes)
                want = {"captions_on": True, "captions_off": False}.get(action, not on)
                p.evaluate("(w) => { const v = document.querySelector('video'); [...v.textTracks].forEach((t, i) => "
                           "t.mode = (w && i === 0) ? 'showing' : 'disabled'); }", want)
                return f"Captions are now {'on' if want else 'off'}."
            elif action == "next":
                if not yt:
                    return "Error: 'next video' only works on YouTube."
                p.keyboard.press("Shift+N")
                self._settle(4000)
            elif action in ("skip_ad", "skip"):
                btn = p.locator(".ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern, button:has-text('Skip')")
                ad_showing = p.evaluate("() => !!document.querySelector('.ad-showing, .ytp-ad-player-overlay, .ytp-ad-text')")
                if btn.count() == 0 or not btn.first.is_visible():
                    if action == "skip" and yt and not ad_showing:
                        p.keyboard.press("Shift+N")  # nothing to skip → next video
                        self._settle(4000)
                        return f"Skipped to the next video: {re.sub(r'\\s*-\\s*YouTube$', '', p.title())}."
                    if ad_showing:
                        return "There's an ad, but it can't be skipped yet – the Skip button appears after a few seconds."
                    return "There's no ad playing right now."
                if p.evaluate("() => !!document.fullscreenElement"):
                    p.evaluate("() => document.exitFullscreen()")
                btn.first.click(timeout=4000)
            elif action != "status":
                return f"Error: unknown video action '{action}'."
            p.wait_for_timeout(250)
            st = p.evaluate("() => { const v = document.querySelector('video'); return {paused: v.paused, t: Math.floor(v.currentTime),"
                            " d: Math.floor(v.duration || 0), muted: v.muted, vol: Math.round(v.volume*100), rate: v.playbackRate,"
                            " fs: !!document.fullscreenElement}; }")
            title = re.sub(r"\s*-\s*YouTube$", "", p.title())
            fmt = lambda x: f"{x // 60}:{x % 60:02d}"
            return (f"{title}: {'paused' if st['paused'] else 'playing'} at {fmt(st['t'])} of {fmt(st['d'])}"
                    f"{', muted' if st['muted'] else ''}, volume {st['vol']}%{', speed ' + str(st['rate']) + 'x' if st['rate'] != 1 else ''}"
                    f"{', full screen' if st['fs'] else ''}.")

        return self.call(job)

    def window(self, state: str) -> str:
        """Maximize / minimize / fullscreen / restore Zoha's browser window (Chromium DevTools protocol)."""
        def job():
            self._ensure()
            cdp = self.ctx.new_cdp_session(self.page)
            wid = cdp.send("Browser.getWindowForTarget")["windowId"]
            target = {"maximize": "maximized", "minimize": "minimized", "fullscreen": "fullscreen", "restore": "normal"}[state]
            cur = cdp.send("Browser.getWindowBounds", {"windowId": wid})["bounds"].get("windowState")
            if cur != "normal" and target != "normal":
                cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
            cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": target}})
            if target != "minimized":
                self.page.bring_to_front()
            return {"maximized": "Maximized my browser window.", "minimized": "Minimized my browser.",
                    "fullscreen": "My browser is now full screen (press F11 or ask me to restore it).",
                    "normal": "Restored my browser window."}[target]

        return self.call(job)

    def look(self):
        """Screenshot of the visible page with each interactive element's [number] drawn on it (for vision models)."""
        def job():
            self._ensure()
            p = self.page
            items = p.evaluate(SNAPSHOT_JS, 80)
            p.evaluate("""() => {
                const box = document.createElement('div'); box.id = '__zoha_marks';
                box.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:2147483647';
                for (const el of document.querySelectorAll('[data-zoha-ref]')) {
                  const r = el.getBoundingClientRect();
                  if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
                  const o = document.createElement('div');
                  o.style.cssText = `position:fixed;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;` +
                                    'outline:2px solid #ff2d55;outline-offset:-1px';
                  const t = document.createElement('span'); t.textContent = el.getAttribute('data-zoha-ref');
                  t.style.cssText = 'position:absolute;left:-2px;top:-2px;background:#ff2d55;color:#fff;font:bold 11px/13px Arial;' +
                                    'padding:0 3px;border-radius:3px';
                  o.appendChild(t); box.appendChild(o);
                }
                document.documentElement.appendChild(box);
            }""")
            try:
                img = p.screenshot(type="jpeg", quality=70, full_page=False)
            finally:
                p.evaluate("() => { const b = document.getElementById('__zoha_marks'); if (b) b.remove(); }")
            return img, f"Tab: {p.title()} | {p.url}\n" + "\n".join(items)

        return self.call(job)

    def is_open(self) -> bool:
        return self.ctx is not None and self._thread is not None and self._thread.is_alive()

    def current_url(self) -> str:
        if not self.is_open():
            return ""
        try:
            return self.call(lambda: self.page.url if self._alive() else "", timeout=5)
        except Exception:
            return ""

    def close(self) -> str:
        def job():
            self._close_all()
            return "Closed my browser."

        return self.call(job)


_BROWSER: Optional[Browser] = None


def get_browser() -> Browser:
    global _BROWSER
    if _BROWSER is None:
        _BROWSER = Browser(os.getenv("BROWSER_CHANNEL", "auto").strip().lower() or "auto")
    return _BROWSER


def shutdown():
    if _BROWSER is not None:
        _BROWSER.shutdown()
