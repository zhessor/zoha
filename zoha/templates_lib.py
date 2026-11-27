"""
Zoha's template library: professional, freely licensed website templates she fills in for a business.

Ships with 17 Start Bootstrap templates (MIT licence – free for commercial and client work).
You can add your own: put any template folder (with an index.html) into <project>/templates/<name>/,
optionally with a template.json {"name", "good_for", "description", "license", "credit"}.
(HTML5 UP designs are CC BY 3.0 – fine for client work if the footer keeps "Design: HTML5 UP".)
"""
from __future__ import annotations

import json
import random
import re
import shutil
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def templates() -> dict:
    out = {}
    if not TEMPLATES_DIR.is_dir():
        return out
    for d in sorted(TEMPLATES_DIR.iterdir()):
        if not (d / "index.html").exists():
            continue
        meta = {"id": d.name, "name": d.name.replace("-", " ").title(), "good_for": "", "description": "", "license": "see folder"}
        try:
            meta.update(json.loads((d / "template.json").read_text(encoding="utf-8")))
        except Exception:
            pass
        meta["dir"] = d
        out[d.name] = meta
    return out


def pick(request: str, rng: random.Random | None = None) -> dict | None:
    """The template that fits the request best: named explicitly, else by 'good_for' word overlap."""
    lib = templates()
    if not lib:
        return None
    t = (request or "").lower()
    for tid, m in lib.items():
        if re.search(r"\b" + re.escape(tid.replace("-", " ")) + r"\b|\b" + re.escape(tid) + r"\b", t):
            return m
    words = set(re.findall(r"[a-z]{3,}", t))
    scored = []
    for m in lib.values():
        good = set(re.findall(r"[a-z]{3,}", m.get("good_for", "").lower()))
        s = len(words & good)
        if s:
            scored.append((s, m["id"], m))
    if not scored:
        return None
    best = max(s for s, _, _ in scored)
    top = [m for s, _, m in scored if s == best]
    return (rng or random).choice(top)


def compact(html: str) -> str:
    """Shorter for the model: no comments, no indentation (same page)."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"\n\s*\n+", "\n", html)
    return "\n".join(line.strip() for line in html.splitlines() if line.strip())


def prepare(meta: dict, page_path: Path) -> str:
    """Copy the template's assets next to the page (<page>_files/) and return its HTML with paths rewritten."""
    src: Path = meta["dir"]
    files = page_path.parent / f"{page_path.stem}_files"
    if files.exists():
        shutil.rmtree(files, ignore_errors=True)
    shutil.copytree(src, files, ignore=shutil.ignore_patterns("index.html", "*.md"))
    html = (src / "index.html").read_text(encoding="utf-8", errors="replace")

    def fix(m):
        attr, q, url = m.group(1), m.group(2), m.group(3)
        if re.match(r"(?:[a-z]+:|//|#|/)", url, re.I) or not url:
            return m.group(0)
        return f"{attr}={q}{files.name}/{url}{q}"
    html = re.sub(r"\b(src|href)=([\"'])([^\"']*)\2", fix, html)
    html = re.sub(r"url\((['\"]?)(?![a-z]+:|/|#)([^)'\"]+)\1\)", lambda m: f"url({m.group(1)}{files.name}/{m.group(2)}{m.group(1)})", html)
    return compact(html)


def prompt_for(meta: dict, name: str, what: str, html: str, year: int) -> str:
    return (
        f"Make the web page {name}. Request: {what}\n\n"
        f"Use this professional template: {meta.get('name')} – {meta.get('description', '')}\n"
        "Rewrite it for THIS business:\n"
        "- Replace ALL visible text: headings, paragraphs, buttons, nav labels, sample names, prices, testimonials, team,"
        " addresses, phone numbers, footer – with real, specific content for this business (Indian context: ₹ prices with"
        f" Indian grouping, +91 numbers, real Mumbai/Indian areas, © {year}). No lorem ipsum, no 'Your Website', no sample company names.\n"
        "- KEEP the HTML structure, class names, ids, scripts and every link to the template's css/js/images exactly as they are.\n"
        "- Rename or remove sections that don't fit the business; keep nav links matching section ids.\n"
        "- In <head>: a specific <title>, <meta name=\"description\"> (140–160 chars), og:title/og:description/og:type, and a"
        " <script type=\"application/ld+json\"> LocalBusiness block.\n"
        "- Add a floating WhatsApp link (<a class=\"wa-float\" href=\"https://wa.me/91XXXXXXXXXX\">WhatsApp</a>) before </body>"
        " with a small <style> for it (fixed, bottom-right, green #25D366).\n"
        "- Every form input needs a <label>. No alert().\n\n"
        f"TEMPLATE:\n{html}\n\nOutput ONLY the complete finished HTML file – no explanation, no markdown fences."
    )
