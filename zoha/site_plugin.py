"""
Website/CMS plugin — Zoha reads and changes YOUR website through a small "Agent API" (see docs/site-agent-api.md).
Off unless SITE_API_URL and SITE_API_KEY are set in .env.

Safety (enforced in three places):
  * the website itself only changes on POST /changes/{id}/apply, valid once and for 5 minutes;
  * the AI has NO apply tool – it can only *propose*; the engine calls apply only when the very next
    thing the user says is a clear "yes" to the summary just read out (see engine._turn);
  * anything other than yes/no cancels the waiting change, so a later "yes" can't apply a stale proposal.

The key (SITE_API_KEY in .env) is only ever placed in the Authorization header: never logged,
spoken, put in URLs or in error messages.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from .tools import CTX, REGISTRY, tool

log = logging.getLogger("zoha.site")
SITE = (os.getenv("SITE_NAME") or "your website").strip()
WINDOW = 5 * 60          # a proposal can be confirmed for 5 minutes (same as the server)
TIMEOUT = 12.0
SLOW_TIMEOUT = 35.0      # analytics asks PostHog and can take a while


class SiteError(Exception):
    pass


class Expired(SiteError):
    """410 – the pending change/draft ran out (5 min)."""


# ── HTTP client ─────────────────────────────────────────────────────────────
def _conf() -> Tuple[str, str]:
    return (os.getenv("SITE_API_URL", "").rstrip("/"),
            (os.getenv("SITE_API_KEY") or "").strip().strip('"').strip("'"))


def _req(method: str, path: str, body: Optional[dict] = None, timeout: float = TIMEOUT, _retry: bool = True) -> dict:
    base, key = _conf()
    if not key:
        raise SiteError("The website key isn't set up yet (SITE_API_KEY in Zoha's .env), so I can't reach the site.")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                          "Accept": "application/json", "User-Agent": "Zoha/1"})
    status, payload = 0, {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
            payload = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            payload = json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:
            payload = {}
        if status == 429 and _retry:
            wait = min(30.0, float(e.headers.get("Retry-After") or 5))
            _log(method, path, status, body)
            time.sleep(wait)
            return _req(method, path, body, timeout, _retry=False)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        _log(method, path, 0, body)
        reason = "it took too long to answer" if "timed out" in str(e).lower() else "I couldn't reach it"
        raise SiteError(f"The website didn't respond ({reason}). Try again in a bit.") from None
    _log(method, path, status, body, payload)
    if status < 400:
        return payload
    err = str(payload.get("error") or "").strip()[:240]
    if status == 500 and "configured" in err.lower():
        raise SiteError("The website's email isn't set up yet, so I can't send replies.")
    if status == 502 and "/apply" in path and "/replies/" in path:
        raise SiteError("The email provider failed, so nothing was sent. Want me to try again?")
    if status == 410:
        raise Expired("expired")
    raise SiteError({
        401: "I can't authenticate with the website (the key is wrong or missing).",
        400: f"The website rejected that: {err or 'invalid request'}.",
        404: f"The website couldn't find that{': ' + err if err else ''}.",
        409: "That change is out of date (it was already used, or the content changed since). I'll need to check again and re-propose.",
        410: "That change expired. I'll need to propose it again.",
        429: "The website is getting too many requests right now. Try again in a minute.",
    }.get(status, "The website is having trouble right now (server error)." if status >= 500 else f"The website said no ({status})."))


def _log(method: str, path: str, status: int, body=None, payload=None):
    """Method, path (no query text), status, change id. Never the key or full bodies."""
    cid = (payload or {}).get("changeId") if isinstance(payload, dict) else None
    m = re.search(r"/changes/([^/?]+)", path)
    log.info("site %s %s → %s%s", method, path.split("?")[0], status or "no answer", f" change={cid or m.group(1)}" if (cid or m) else "")


# ── describe (cached) → tool help text ──────────────────────────────────────
_DESC: Dict[str, Any] = {"data": None, "t": 0.0}


def describe(force: bool = False) -> dict:
    if force or not _DESC["data"] or time.time() - _DESC["t"] > 6 * 3600:
        _DESC["data"], _DESC["t"] = _req("GET", "/describe"), time.time()
        _refresh_help()
    return _DESC["data"]


def _fields_text(d: dict) -> str:
    out = []
    for t in d.get("types", []):
        fs = []
        for f in t.get("fields", []):
            kind = "|".join(f["values"]) if f.get("values") else f.get("kind", "string")
            fs.append(f"{f['name']}({kind}{', required' if f.get('required') else ''}{', max ' + str(f['max']) if f.get('max') else ''})")
        out.append(f"{t['type']}{' [single]' if t.get('singleton') else ''} – {'/'.join(t.get('actions', []))}: {', '.join(fs)}")
    return "\n".join(out)


def _refresh_help():
    d = _DESC["data"] or {}
    if d.get("types") and "site_propose" in REGISTRY:
        REGISTRY["site_propose"].description = PROPOSE_HELP + " Editable fields:\n" + _fields_text(d)


def warm():
    """Load /describe in the background at start-up (no-op without a key)."""
    if _conf()[1]:
        threading.Thread(target=lambda: _safe(describe), daemon=True, name="zoha-site-describe").start()


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        log.info("site: %s", str(e)[:160])


# ── the change waiting for a yes ────────────────────────────────────────────
_PENDING: Dict[str, Any] = {}       # {"id", "summary", "until"}
_LAST_APPLIED: Dict[str, Any] = {}  # {"id", "summary", "t"}  → "undo that"


def pending_site() -> Optional[dict]:
    if _PENDING and time.time() < _PENDING["until"]:
        return dict(_PENDING)
    _PENDING.clear()
    return None


def _ask(change: dict, prefix: str = "", redo: Optional[Tuple[str, dict]] = None) -> str:
    summary = str(change.get("summary") or "a change to the website").strip().rstrip(".")
    _PENDING.clear()
    _PENDING.update(kind="change", id=change["changeId"], summary=summary, until=time.time() + WINDOW, redo=redo, prefix=prefix)
    q = f"On {SITE} (live): {prefix}{summary}. Should I go ahead?"
    return f"NOT DONE YET. Ask the user exactly: '{q}' Do nothing else."


def _ask_reply(draft: dict, redo: Tuple[str, dict]) -> str:
    em = draft.get("email") or {}
    to = str(em.get("to") or "them").strip()
    body = str(em.get("body") or "").strip()
    greet = str(em.get("greeting") or "").strip()
    _PENDING.clear()
    _PENDING.update(kind="reply", id=draft["replyId"], summary=str(draft.get("summary") or f"Reply to {to}").strip(),
                    until=time.time() + WINDOW, redo=redo, to=to)
    again = f" Note: you've already replied to {to} before." if em.get("alreadyReplied") else ""
    q = f"Here's the email to {to}: {(greet + ' ') if greet else ''}{body}{again} Should I send it?"
    return f"NOT DONE YET. Ask the user exactly: '{q}' Do nothing else."


def apply_pending() -> str:
    """Called by the ENGINE (never by the AI) after the user says yes to the exact text just read out."""
    p = pending_site()
    if not p:
        return "There's no website change or email waiting – nothing was done."
    _PENDING.clear()
    path = (f"/replies/{urllib.parse.quote(p['id'])}/apply" if p.get("kind") == "reply"
            else f"/changes/{urllib.parse.quote(p['id'])}/apply")
    try:
        _req("POST", path, {})
    except Expired:
        # ran out of time: make a fresh draft/proposal from the same request and ASK AGAIN – never send/apply it automatically
        if p.get("redo"):
            try:
                fresh = _req("POST", p["redo"][0], p["redo"][1])
            except SiteError as e:
                return f"Error: that expired, and re-preparing it failed: {e}"
            q = _ask_reply(fresh, p["redo"]) if p.get("kind") == "reply" else _ask(fresh, p.get("prefix", ""), p["redo"])
            return "EXPIRED: " + q
        return "Error: that expired before you confirmed it. Ask me again and I'll prepare it fresh."
    except SiteError as e:
        return f"Error: {e}"
    if p.get("kind") == "reply":
        return f"Sent. Your reply to {p.get('to', 'them')} is on its way."
    _LAST_APPLIED.update(id=p["id"], summary=p["summary"], t=time.time())
    return f"Done, it's live on the website: {p['summary'][0].lower() + p['summary'][1:]}. Say undo that if you want it back."


def cancel_pending(say: bool = True) -> str:
    p = pending_site()
    _PENDING.clear()
    if p:
        _safe(_req, "POST", f"/changes/{urllib.parse.quote(p['id'])}/cancel", {})
    if not say:
        return ""
    return "Okay, I won't send it." if p and p.get("kind") == "reply" else "Okay, cancelled. Nothing changed on the website."


# "yes" for a waiting website change / email: plain yes words, or the action itself ("send it", "publish it", "haan bhej do")
CONFIRM_RX = re.compile(r"^\W*(?:(?:the|my) answer is|i said|i say|it'?s a)?\W*(?:(?:yes|yeah|yep|yup|ya|haan|ha|ok(?:ay)?|sure|alright|perfect|great|looks good|sounds good)\W*)*"
                        r"(?:(?:yes|yeah|yep|yup|ya|haan|ha|sure|ok(?:ay)?|confirm(?:ed)?|absolutely|correct|perfect|looks good|sounds good|"
                        r"(?:please |just |go ahead and )?(?:send|send it|send that|send the (?:email|mail|reply)|shoot it|"
                        r"apply|apply it|publish|publish it|post it|make (?:the|that) change|change it|update it|do it|do that|go ahead|go for it|"
                        r"please do|bhej do|bhejo|bhej de|kar do|karo)))"
                        r"(?:\W+(?:it|now|then|please|zoha|bro|yaar|na|da|thanks|thank you|thing|do it|go ahead))*\W*$", re.I)
EDIT_RX = re.compile(r"\b(?:but|change|instead|edit|wait|actually|tomorrow|later|except|without|add|remove|replace|rewrite|different|another)\b", re.I)


def is_confirm(text: str) -> bool:
    """A clear yes to the exact thing just read out – and nothing that sounds like an edit."""
    return bool(CONFIRM_RX.match(text or "")) and not EDIT_RX.search(text or "")
NO_RX = re.compile(r"^\W*(?:no|nope|nah|nahi|na|cancel|don'?t|do not|stop|wait|leave it|never ?mind|not now|rehne do|mat karo)\b", re.I)


# ── tools (what the AI can do) ──────────────────────────────────────────────
def _compact(items, keys=None, limit=12) -> str:
    rows = []
    for it in items[:limit]:
        bits = [f"{k}={json.dumps(v, ensure_ascii=False)[:120]}" for k, v in it.items() if (keys is None or k in keys) and v not in (None, "", [])]
        rows.append("- " + "; ".join(bits))
    return "\n".join(rows) or "(nothing)"


@tool("site_read", "Read the current content of the user's website – pricing plans, testimonials, work items, the "
      "announcement bar, the website-score popup, blog posts. Returns items WITH their ids; use it to find the id before proposing a change.",
      "Reading the website", "🌐",
      type=("string", "What to read (leave out to see your recent changes)", False, ["pricing", "testimonial", "work", "announcement", "lead-magnet", "post"]),
      q=("string", "Optional search text, e.g. 'Business'", False),
      id=("string", "Optional exact id", False))
def site_read(type: str = "", q: Optional[str] = None, id: Optional[str] = None) -> str:
    if not type:   # "where did you add it?" – show what was changed recently instead of failing
        return site_changes()
    params = {"type": type}
    if q:
        params["q"] = q
    if id:
        params["id"] = id
    try:
        d = _req("GET", "/read?" + urllib.parse.urlencode(params))
    except SiteError as e:
        return f"Error: {e}"
    items = d.get("items") or []
    if type == "post":
        items = [{k: (v[:160] + "…" if k == "body" and isinstance(v, str) and len(v) > 160 else v) for k, v in it.items()} for it in items]
    return f"{d.get('count', len(items))} {type} item(s) on {SITE}:\n" + _compact(items)


@tool("site_enquiries", "Latest enquiries from the user's website contact form (name, source, status, date, message) and the unread count.",
      "Website enquiries", "📨", limit=("integer", "How many (default 5)", False))
def site_enquiries(limit: int = 5) -> str:
    try:
        d = _req("GET", f"/enquiries?limit={max(1, min(20, int(limit or 5)))}")
    except SiteError as e:
        return f"Error: {e}"
    items = d.get("items") or []
    head = f"{d.get('unread', 0)} unread. "
    return head + ("No enquiries yet." if not items else f"Latest {len(items)}:\n" + _compact(items, ["id", "name", "source", "status", "date", "createdAt", "message"]))


@tool("site_analytics", "Website analytics summary for the user's website: visitors and other KPIs vs the previous period, top pages, top sources, conversions.",
      "Website analytics", "📈", range=("string", "Period", False, ["today", "7d", "30d", "90d"]))
def site_analytics(range: str = "7d") -> str:
    try:
        d = _req("GET", "/analytics?range=" + urllib.parse.quote(range or "7d"), timeout=SLOW_TIMEOUT)
    except SiteError as e:
        return f"Error: {e}"
    if d.get("configured") is False:
        return "Website analytics isn't set up yet."
    return "Analytics (" + (range or "7d") + "): " + json.dumps(d, ensure_ascii=False)[:1500]


PROPOSE_HELP = ("PROPOSE a change to the user's website. This does NOT change the site: it returns a summary that is read "
                "to the user, and the site only changes if they say yes. Get the id from site_read first (never invent ids; announcement "
                "and lead-magnet need no id). There are no deletes; send an empty string to clear an optional field. If the request "
                "is ambiguous (which plan? which post?), ask the user first instead of proposing.")


@tool("site_propose", PROPOSE_HELP, "Preparing a website change", "📝",
      type=("string", "Content type", True, ["pricing", "testimonial", "work", "announcement", "lead-magnet", "post"]),
      action=("string", "update an existing item or create a new one", True, ["update", "create"]),
      fields=("object", "Only the fields to change, e.g. {\"salePrice\": \"₹8,999\", \"saleLabel\": \"Diwali offer\"}", True),
      id=("string", "Id of the item to update (from site_read)", False),
      reason=("string", "Optional short reason", False))
def site_propose(type: str, action: str, fields: dict, id: Optional[str] = None, reason: Optional[str] = None) -> str:
    if not isinstance(fields, dict) or not fields:
        return "Error: say which fields to change."
    body = {"type": type, "action": action, "fields": fields}
    if id:
        body["id"] = id
    if reason:
        body["reason"] = str(reason)[:200]
    try:
        change = _req("POST", "/changes", body)
    except SiteError as e:
        return f"Error: {e}"
    if not change.get("changeId"):
        return "Error: the website didn't return a change to confirm."
    cancel_pending(say=False)  # only ONE change waits at a time – a newer proposal replaces an older one
    return _ask(change, redo=("/changes", body))


@tool("site_undo", "Undo a change Zoha made on the user's website (default: the last one). This only PROPOSES the undo; the user confirms it.",
      "Preparing an undo", "↩", change_id=("string", "Which change to undo (default: the last applied one)", False))
def site_undo(change_id: Optional[str] = None) -> str:
    cid = change_id or _LAST_APPLIED.get("id")
    if not cid:
        try:
            hist = _req("GET", "/changes?limit=10").get("changes") or []
        except SiteError as e:
            return f"Error: {e}"
        last = next((c for c in hist if c.get("status") == "applied" and not c.get("reverted")), None)
        if not last:
            return "There's no website change of mine to undo."
        cid = last.get("id")
    try:
        change = _req("POST", "/undo", {"changeId": cid})
    except SiteError as e:
        if change_id and "no such change" in str(e).lower():   # the model invented an id – use the real last change
            return site_undo(None)
        if "can't be reverted" in str(e).lower() or "cannot be reverted" in str(e).lower():
            return (f"Error: {e} I can't delete items on {SITE} – tell the user to remove it in the admin "
                    "(Work → the item → delete), or offer to hide it by changing it.")
        return f"Error: {e}"
    cancel_pending(say=False)
    return _ask(change, prefix="To undo it: ", redo=("/undo", {"changeId": cid}))


@tool("site_changes", "What Zoha changed on the user's website recently (history with status).", "Website change history", "🗂",
      limit=("integer", "How many (default 10)", False))
def site_changes(limit: int = 10) -> str:
    try:
        d = _req("GET", f"/changes?limit={max(1, min(30, int(limit or 10)))}")
    except SiteError as e:
        return f"Error: {e}"
    ch = d.get("changes") or []
    return "No website changes yet." if not ch else _compact(ch, ["summary", "status", "kind", "action", "type", "appliedAt", "createdAt", "reverted"], 30)


@tool("site_enquiry_reply", "DRAFT an email reply to a website enquiry (nothing is sent: the draft is read to the user and only sent after "
      "their yes). Get the enquiry id from site_enquiries first; if several could match, ask which one. Write plain text, no markdown, "
      "under 2000 characters, WITHOUT a greeting or signature (the website adds 'Hey <name>,' and the sign-off). Use the user's own "
      "words when they dictate; otherwise a short polite draft. Never invent prices, dates, meeting times or promises – ask the user.",
      "Drafting an email reply", "✉",
      enquiry_id=("string", "Id of the enquiry (from site_enquiries)", True),
      body=("string", "The reply text (no greeting, no signature)", True))
def site_enquiry_reply(enquiry_id: str, body: str) -> str:
    text = (body or "").strip()
    stripped = re.sub(r"^(?:hi|hello|hey|dear|namaste)\b[^,!\n]{0,30}[,!]\s*", "", text, flags=re.I).strip()
    text = stripped or text  # only a leading "Hello Sam," – the website adds its own greeting
    if not text:
        return "Error: the reply is empty – what should it say?"
    if len(text) > 2000:
        return "Error: that reply is too long (over 2000 characters) – shorten it."
    path, payload = f"/enquiries/{urllib.parse.quote(str(enquiry_id))}/reply", {"body": text}
    try:
        draft = _req("POST", path, payload)
    except SiteError as e:
        return f"Error: {e}"
    if not draft.get("replyId"):
        return "Error: the website didn't return a draft to confirm."
    cancel_pending(say=False)  # a new draft replaces any older one – a yes only ever counts for the latest text
    return _ask_reply(draft, (path, payload))


@tool("site_enquiry_status", "Archive a website enquiry, or put it back to new. Reversible and emails nobody, so no confirmation is needed.",
      "Updating an enquiry", "🗃",
      enquiry_id=("string", "Id of the enquiry (from site_enquiries)", True),
      status=("string", "New status", True, ["archived", "new"]))
def site_enquiry_status(enquiry_id: str, status: str) -> str:
    try:
        _req("POST", f"/enquiries/{urllib.parse.quote(str(enquiry_id))}/status", {"status": status})
    except SiteError as e:
        return f"Error: {e}"
    return "Archived it." if status == "archived" else "Moved it back to new."
