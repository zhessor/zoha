"""
Install a skill from a URL.

    python -m zoha.skill_install install https://github.com/user/repo/blob/main/skills/email.md
    python -m zoha.skill_install list

A skill is a Markdown file with a `name` / `description` header (the same layout as
agentskills.io SKILL.md files). It is plain text that Zoha reads as instructions; it
never runs code. Installing one only saves that text into `skills/`.
"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .tools import SKILLS_DIR, skill_meta

MAX_BYTES = 64 * 1024
SLUG = re.compile(r"[^a-z0-9]+")


class SkillError(Exception):
    pass


def raw_url(url: str) -> str:
    """Turn a github.com 'blob' link into the raw file link; leave other links alone."""
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/blob/(.+)", url.strip())
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return url.strip()


def _fetch(url: str) -> str:
    if not url.startswith("https://"):
        raise SkillError("Only https links are accepted.")
    req = urllib.request.Request(url, headers={"User-Agent": "zoha-skill-install"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SkillError("That file is larger than 64 KB, which is too big for a skill.")
    return data.decode("utf-8")


def slugify(name: str) -> str:
    return SLUG.sub("-", name.lower()).strip("-")[:48]


def install(url: str, *, force: bool = False, fetch: Optional[Callable[[str], str]] = None,
            skills_dir: Optional[Path] = None) -> Path:
    """Download, check and save one skill. Returns the saved path."""
    text = (fetch or _fetch)(raw_url(url))
    meta = skill_meta(text)
    if not meta.get("name") or not meta.get("description"):
        raise SkillError("This file has no name/description header, so it isn't a skill.")
    slug = slugify(meta["name"])
    if not slug:
        raise SkillError("The skill name has no usable letters.")
    dest = (skills_dir or SKILLS_DIR) / f"{slug}.md"
    if dest.exists() and not force:
        raise SkillError(f"{dest.name} already exists. Use --force to replace it.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


def list_skills(skills_dir: Optional[Path] = None) -> list:
    out = []
    for p in sorted((skills_dir or SKILLS_DIR).glob("*.md")):
        meta = skill_meta(p.read_text(encoding="utf-8"))
        out.append((p.stem, meta.get("description", "")))
    return out


def main(argv: Optional[list] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["list"]:
        for name, desc in list_skills():
            print(f"{name:20} {desc[:80]}")
        return 0
    if args[:1] == ["install"] and len(args) >= 2:
        try:
            path = install(args[1], force="--force" in args)
        except (SkillError, OSError, UnicodeDecodeError) as e:
            print(f"Could not install: {e}")
            return 1
        print(f"Installed {path.name}. Restart Zoha to use it.")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
