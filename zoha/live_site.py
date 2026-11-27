"""
Publish the page Zoha just built to the web (Netlify). Talk a site into existence, then say "publish it".

Safety: the AI can only ask; the deploy runs after a clear yes (zoha.confirm). Needs NETLIFY_TOKEN in .env,
which is only ever sent in the Authorization header and never logged or spoken.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from . import confirm
from .config import DATA_DIR
from .tools import CTX, tool

log = logging.getLogger("zoha.live_site")
API = "https://api.netlify.com/api/v1"
MAX_ZIP = 40 * 1024 * 1024
SKIP_SUFFIX = {".py", ".env", ".key", ".pem", ".log"}


class PublishError(Exception):
    pass


def _token() -> str:
    return (os.getenv("NETLIFY_TOKEN") or "").strip().strip('"').strip("'")


def _registry() -> Path:
    return DATA_DIR / "published_sites.json"


def _load() -> dict:
    try:
        return json.loads(_registry().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict) -> None:
    _registry().parent.mkdir(parents=True, exist_ok=True)
    _registry().write_text(json.dumps(d, indent=1), encoding="utf-8")


def build_zip(page: Path) -> bytes:
    """index.html plus the page's sibling '<name>_files' / '<name>_photos' folders. Nothing else leaves the PC."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(page, "index.html")
        for suffix in ("_files", "_photos"):
            folder = page.parent / f"{page.stem}{suffix}"
            if folder.is_dir():
                for f in folder.rglob("*"):
                    if f.is_file() and f.suffix.lower() not in SKIP_SUFFIX and not f.name.startswith("."):
                        z.write(f, f"{folder.name}/{f.relative_to(folder).as_posix()}")
    data = buf.getvalue()
    if len(data) > MAX_ZIP:
        raise PublishError("The site is bigger than 40 MB, which is too large to publish this way.")
    return data


def _call(method: str, path: str, body: bytes, ctype: str, token: str) -> dict:
    req = urllib.request.Request(API + path, data=body, method=method,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": ctype, "User-Agent": "Zoha/1"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        raise PublishError("Netlify refused it" + (" (the token looks wrong)" if e.code in (401, 403) else f" (error {e.code})")) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise PublishError("I couldn't reach Netlify. Check the internet and try again.") from None


def deploy(page: Path, token: str, call=_call) -> str:
    """Create (or update) the site and return its public URL."""
    reg = _load()
    key = str(page.resolve())
    site_id = reg.get(key, {}).get("site_id")
    if not site_id:
        made = call("POST", "/sites", b"{}", "application/json", token)
        site_id = made.get("id")
        if not site_id:
            raise PublishError("Netlify didn't create the site.")
        reg[key] = {"site_id": site_id}
    dep = call("POST", f"/sites/{site_id}/deploys", build_zip(page), "application/zip", token)
    url = dep.get("ssl_url") or dep.get("url") or reg[key].get("url") or ""
    if not re.match(r"^https://", url or ""):
        raise PublishError("The deploy finished but Netlify gave no web address.")
    reg[key]["url"] = url
    _save(reg)
    return url


def _resolve(filename: str) -> Optional[Path]:
    from .tools import find_named
    if filename and filename.strip().lower() not in ("it", "that", "this", "last", "the page", "the website", "the site"):
        p = find_named(filename)
        if p:
            return Path(p)
    if CTX.last_file and Path(CTX.last_file).exists():
        return Path(CTX.last_file)
    return None


@tool("site_publish", "Put a web page Zoha made on the internet at a free public link. Use for 'publish it', 'put it online', "
      "'make it live', 'deploy my website'. Leave filename out for the page Zoha made last. It only ASKS the user first; "
      "it publishes after they say yes.", "Publish page", "🚀",
      filename=("string", "The page to publish (spoken name is fine), or leave out for the last page", False))
def site_publish(filename: str = "") -> str:
    token = _token()
    if not token:
        return ("Error: publishing isn't set up. Tell the user to add NETLIFY_TOKEN to Zoha's .env "
                "(a free Netlify personal access token), then ask again.")
    page = _resolve(filename)
    if not page or page.suffix.lower() not in (".html", ".htm"):
        return "Error: I couldn't find a web page to publish. Ask the user which page, or build one first."

    def run() -> str:
        try:
            url = deploy(page, _token())
        except PublishError as e:
            return f"Error: {e}"
        return f"Published. Your site is live at {url}"

    return confirm.request("publish", f"I'll put {page.name} on the internet at a public Netlify link, so anyone with it can see the page.", run)
