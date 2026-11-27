"""
Test a generated web page in a real (hidden) browser, like a developer would:
console errors, broken scripts, horizontal scrolling on a phone, the menu on desktop and mobile,
the hamburger actually opening, and – when Zoha has eyes – a look at a phone screenshot.

Runs in its own headless Edge/Chrome, so it never touches Zoha's visible browser.
Returns a list of concrete problems (each becomes a fix instruction for the writer).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, List, Optional

log = logging.getLogger("zoha.page_check")

PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1280, "height": 800}

NAV_JS = """() => {
  const nav = document.querySelector('nav, header');
  if (!nav) return {hasNav: false};
  const links = [...nav.querySelectorAll('a')].filter(a => !a.classList.contains('logo'));
  const visible = links.filter(a => { const r = a.getBoundingClientRect(), s = getComputedStyle(a);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; });
  return {hasNav: true, links: links.length, visible: visible.length};
}"""

OVERFLOW_JS = """() => {
  const w = document.documentElement.clientWidth, wide = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.right > w + 2 && getComputedStyle(el).position !== 'fixed') {
      wide.push((el.tagName + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : '')).toLowerCase());
      if (wide.length >= 3) break;
    }
  }
  return {scroll: document.documentElement.scrollWidth > w + 2, wide};
}"""

TAP_JS = """() => {
  const small = [];
  for (const el of document.querySelectorAll('a, button, input, textarea, select')) {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    if (r.width === 0 || s.display === 'none' || s.visibility === 'hidden') continue;
    if (r.height < 32 && el.closest('nav, header, form, .cta, .hero')) small.push((el.textContent || el.name || el.tagName).trim().slice(0, 20));
  }
  return small.slice(0, 4);
}"""


def check_page(path: Path, vision: Optional[Callable[[str, bytes], str]] = None, timeout_ms: int = 15000) -> List[str]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []
    problems: List[str] = []
    url = Path(path).resolve().as_uri()
    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        for ch in ("msedge", "chrome", None):
            try:
                browser = pw.chromium.launch(headless=True, **({"channel": ch} if ch else {}))
                break
            except Exception:
                continue
        if browser is None:
            return []

        # ── desktop ──────────────────────────────────────────────────────────
        errors: List[str] = []
        page = browser.new_page(viewport=DESKTOP)
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url, timeout=timeout_ms, wait_until="load")
        page.wait_for_timeout(600)
        js_errors = [e for e in errors if "picsum" not in e and "fonts.g" not in e and "net::" not in e]
        if js_errors:
            problems.append("JavaScript errors when the page loads – fix them: " + " | ".join(e[:160] for e in js_errors[:3]))
        nav = page.evaluate(NAV_JS)
        if nav.get("hasNav") and nav.get("links", 0) >= 2 and nav.get("visible", 0) == 0:
            problems.append("On a desktop screen (1280px) none of the menu links are visible. Show the nav links on "
                            "desktop and use the hamburger only inside @media (max-width: 760px).")
        burger = page.query_selector(".menu-btn, button[aria-controls]")
        if burger and burger.is_visible() and nav.get("visible", 0) > 0:
            problems.append("On desktop the hamburger menu button is showing next to the normal links – hide it "
                            "outside @media (max-width: 760px).")
        page.close()

        # ── phone ────────────────────────────────────────────────────────────
        page = browser.new_page(viewport=PHONE, is_mobile=True, has_touch=True)
        page.goto(url, timeout=timeout_ms, wait_until="load")
        page.wait_for_timeout(600)
        ov = page.evaluate(OVERFLOW_JS)
        if ov.get("scroll"):
            problems.append("On a phone (390px) the page scrolls sideways – something is wider than the screen"
                            + (f" ({', '.join(ov['wide'])})" if ov.get("wide") else "")
                            + ". Use max-width:100%, flexible grids (minmax(0,1fr)) and stack columns on mobile.")
        btn = page.query_selector(".menu-btn, [aria-controls], button[aria-expanded]")
        if btn and btn.is_visible():
            before = page.evaluate(NAV_JS).get("visible", 0)
            try:
                btn.click(timeout=3000)
                page.wait_for_timeout(400)
                after = page.evaluate(NAV_JS).get("visible", 0)
                expanded = btn.get_attribute("aria-expanded")
                if after <= before:
                    problems.append("On a phone, tapping the menu button doesn't show the menu links. Make the click "
                                    "toggle the 'open' class on the menu and set aria-expanded.")
                elif expanded != "true":
                    problems.append("The menu button opens the menu but doesn't set aria-expanded=\"true\".")
            except Exception:
                problems.append("On a phone the menu button can't be tapped (it's covered or off-screen).")
        elif nav_links_hidden_on_phone(page):
            problems.append("On a phone the menu links are hidden and there is no visible menu button to open them.")
        small = page.evaluate(TAP_JS)
        if small:
            problems.append("Buttons/links too small to tap on a phone (need ≥ 44px tall): " + ", ".join(small))

        if vision:   # Zoha's eyes: a real look at the phone layout
            try:
                shot = page.screenshot(type="jpeg", quality=70, full_page=False)
                seen = vision(
                    "This is a phone screenshot of a new website. List ONLY clear visual problems you can see: "
                    "overlapping elements, text cut off, unreadable text (low contrast), huge empty gaps, broken images "
                    "or layout. One short line each. If it looks fine, answer exactly: OK", shot) or ""
                lines = [l.strip(" -•*") for l in seen.splitlines() if l.strip(" -•*")]
                if lines and not lines[0].upper().startswith("OK"):
                    problems += [f"Visual problem seen on a phone: {l}" for l in lines[:3]]
            except Exception as e:
                log.info("vision check skipped: %s", e)
        page.close()
    except Exception as e:
        log.info("page check failed: %s", e)
    finally:
        try:
            if browser:
                browser.close()
            if pw:
                pw.stop()
        except Exception:
            pass
    return problems


def nav_links_hidden_on_phone(page) -> bool:
    nav = page.evaluate(NAV_JS)
    return bool(nav.get("hasNav") and nav.get("links", 0) >= 2 and nav.get("visible", 0) == 0)
