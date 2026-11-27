"""
Business desk: quotations, unpaid invoices and payment follow-ups by voice.

    "Zoha, make a quotation for Mr Shah: kitchen cabinets 2 at 45000, hob 1 at 12000, with 18 percent GST"
    "Zoha, Mr Shah owes 30000, due on the 5th"      "who hasn't paid?"      "write a follow up for Mr Shah"

Everything stays on this computer (data/business.json). Follow-ups are only DRAFTED for you to copy;
Zoha never sends a message for you. Set BUSINESS_NAME / BUSINESS_PHONE in .env for the header.
"""

import datetime as dt
import html
import json
import os
import re
from pathlib import Path

from zoha.config import DATA_DIR
from zoha.tools import KNOWN, tool

MULT = {"k": 1_000, "thousand": 1_000, "hazaar": 1_000, "hazar": 1_000, "lakh": 100_000, "lac": 100_000, "lakhs": 100_000,
        "crore": 10_000_000, "cr": 10_000_000}
AMOUNT = re.compile(r"(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(k|thousand|hazaar|hazar|lakhs?|lac|crore|cr)?\b", re.I)


def parse_amount(text: str) -> float:
    m = AMOUNT.search(str(text or "").replace("₹", " ₹"))
    if not m:
        raise ValueError(f"no amount in {text!r}")
    n = float(m.group(1).replace(",", ""))
    return n * MULT.get((m.group(2) or "").lower(), 1)


def inr(n: float) -> str:
    """Indian digit grouping: 1234567.5 -> 12,34,567.50"""
    whole, frac = f"{n:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
    return "₹" + (head + "," if head else "") + tail + ("" if frac == "00" else "." + frac)


ITEM = re.compile(r"^\s*(?P<name>.+?)\s*(?:x|×|\bqty\b|\bat\b|@|\bof\b)?\s*$", re.I)


def parse_items(text: str):
    """'Kitchen cabinets x2 @ 45000; Hob x1 @ 12k' -> [(name, qty, rate)]. A missing qty means 1."""
    rows = []
    for part in re.split(r"[;\n]|,\s*(?=[A-Za-z])", text or ""):
        part = part.strip()
        if not part:
            continue
        bare = re.match(r"^(?P<name>.+?)[\s,]+(?P<q>\d+)\s*(?:at|@|rate|for)\s*(?P<rate>(?:₹|rs\.?)?\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:k|thousand|hazaar|lakhs?|lac|crore)?)\s*(?:each)?$", part, re.I)
        if bare:
            rows.append((bare.group("name").strip(" -:"), int(bare.group("q")), parse_amount(bare.group("rate"))))
            continue
        m = re.match(r"^(?P<name>.*?)[\s,]*(?:(?:x|×|qty)\s*(?P<q1>\d+)|(?P<q2>\d+)\s*(?:x|×|nos?|pcs?|units?))?[\s,]*(?:@|at|rate|for|of)?\s*(?P<rate>(?:₹|rs\.?)?\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:k|thousand|hazaar|lakhs?|lac|crore)?)\s*(?:each|per piece)?$", part, re.I)
        if not m or not m.group("name").strip():
            raise ValueError(f"I couldn't read this line: {part!r}")
        qty = int(m.group("q1") or m.group("q2") or 1)
        rows.append((m.group("name").strip(" -:"), qty, parse_amount(m.group("rate"))))
    if not rows:
        raise ValueError("no items")
    return rows


def _db_path() -> Path:
    return DATA_DIR / "business.json"


def _load() -> dict:
    try:
        return json.loads(_db_path().read_text(encoding="utf-8"))
    except Exception:
        return {"invoices": [], "next_quote": 1}


def _save(d: dict) -> None:
    _db_path().parent.mkdir(parents=True, exist_ok=True)
    _db_path().write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


def quote_html(client, rows, gst, number, notes="", valid_days=15, today=None):
    today = today or dt.date.today()
    biz = html.escape(os.getenv("BUSINESS_NAME") or "Your Business")
    phone = html.escape(os.getenv("BUSINESS_PHONE") or "")
    sub = sum(q * r for _, q, r in rows)
    tax = sub * gst / 100
    body = "".join(f"<tr><td>{i}</td><td>{html.escape(n)}</td><td class=r>{q}</td><td class=r>{inr(r)}</td><td class=r>{inr(q * r)}</td></tr>"
                   for i, (n, q, r) in enumerate(rows, 1))
    gst_row = f"<tr><td colspan=4 class=r>GST @ {gst:g}%</td><td class=r>{inr(tax)}</td></tr>" if gst else ""
    note = f"<p class=n>{html.escape(notes)}</p>" if notes else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quotation {number} - {html.escape(client)}</title><style>
body{{font:15px/1.5 system-ui,Segoe UI,Arial,sans-serif;max-width:780px;margin:32px auto;padding:0 20px;color:#1b1f1e}}
h1{{margin:0;font-size:26px}} .top{{display:flex;justify-content:space-between;border-bottom:2px solid #1b1f1e;padding-bottom:12px}}
table{{width:100%;border-collapse:collapse;margin:22px 0}} th,td{{padding:9px 10px;border-bottom:1px solid #ddd;text-align:left}}
th{{background:#f2f4f3}} .r{{text-align:right}} .tot td{{font-weight:700;font-size:17px;border-top:2px solid #1b1f1e}} .n{{color:#555}}
@media print{{body{{margin:0}}}}</style></head><body>
<div class="top"><div><h1>{biz}</h1><div>{phone}</div></div><div class="r"><b>Quotation #{number}</b><br>{today.strftime('%d %b %Y')}<br>Valid {valid_days} days</div></div>
<p>To: <b>{html.escape(client)}</b></p>
<table><tr><th>#</th><th>Item</th><th class=r>Qty</th><th class=r>Rate</th><th class=r>Amount</th></tr>{body}
<tr><td colspan=4 class=r>Subtotal</td><td class=r>{inr(sub)}</td></tr>{gst_row}
<tr class="tot"><td colspan=4 class=r>Total</td><td class=r>{inr(sub + tax)}</td></tr></table>{note}
<p class=n>Prices are valid for {valid_days} days from the date above.</p></body></html>"""


@tool("make_quotation", "Make a quotation/estimate document for a client from spoken items and open it (print to PDF from the browser). "
      "Items look like 'kitchen cabinets 2 at 45000; hob 1 at 12000'.", "Making quotation", "🧾",
      client=("string", "Client name", True), items=("string", "Items with quantity and rate, separated by ; ", True),
      gst_percent=("number", "GST percent to add, e.g. 18 (0 or leave out for none)", False),
      notes=("string", "A short note to print under the table", False))
def make_quotation(client: str, items: str, gst_percent: float = 0, notes: str = "") -> str:
    try:
        rows = parse_items(items)
    except ValueError as e:
        return f"Error: {e}. Ask the user to say each item like 'name, quantity, rate'."
    d = _load()
    number = d.get("next_quote", 1)
    d["next_quote"] = number + 1
    _save(d)
    folder = Path.home() / KNOWN["documents"] / "Zoha Quotes"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Quote-{number:03d}-{re.sub(r'[^A-Za-z0-9]+', '_', client).strip('_')[:30]}.html"
    path.write_text(quote_html(client, rows, float(gst_percent or 0), number, notes), encoding="utf-8")
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]  # Windows
    except Exception:
        pass
    total = sum(q * r for _, q, r in rows) * (1 + float(gst_percent or 0) / 100)
    return f"Quotation {number} for {client}, total {inr(total)}, saved as {path.name} in Documents/Zoha Quotes and opened. Use Print to save it as a PDF."


@tool("add_invoice", "Note an unpaid invoice: who owes how much, and when it is due.", "Noting invoice", "📒",
      client=("string", "Client name", True), amount=("string", "Amount, e.g. 30000 or 1.5 lakh", True),
      due=("string", "Due date in words or YYYY-MM-DD (optional)", False))
def add_invoice(client: str, amount: str, due: str = "") -> str:
    try:
        amt = parse_amount(amount)
    except ValueError:
        return "Error: I couldn't read the amount. Ask the user to say it as a number."
    d = _load()
    d["invoices"].append({"client": client.strip(), "amount": amt, "due": due.strip(), "paid": False,
                          "added": dt.date.today().isoformat()})
    _save(d)
    return f"Noted: {client} owes {inr(amt)}" + (f", due {due}." if due else ".")


def _open_for(client: str = ""):
    c = client.strip().lower()
    return [i for i in _load()["invoices"] if not i["paid"] and (not c or c in i["client"].lower())]


@tool("list_unpaid", "List who hasn't paid yet and how much.", "Checking unpaid", "📋")
def list_unpaid() -> str:
    rows = _open_for()
    if not rows:
        return "Nobody owes anything right now."
    total = sum(r["amount"] for r in rows)
    return "; ".join(f"{r['client']} {inr(r['amount'])}" + (f" (due {r['due']})" if r["due"] else "") for r in rows) + f". Total {inr(total)}."


@tool("mark_paid", "Mark a client's unpaid invoice(s) as paid.", "Marking paid", "✅", client=("string", "Client name", True))
def mark_paid(client: str) -> str:
    d = _load()
    c = client.strip().lower()
    n = 0
    for i in d["invoices"]:
        if not i["paid"] and c and c in i["client"].lower():
            i["paid"] = True
            n += 1
    _save(d)
    return f"Marked {n} invoice(s) from {client} as paid." if n else f"Error: no unpaid invoice found for {client}."


@tool("draft_followup", "Write a polite payment reminder message the user can copy. It NEVER sends anything.", "Drafting reminder", "✍️",
      client=("string", "Client name", True), language=("string", "english (default) or hinglish", False, ["english", "hinglish"]))
def draft_followup(client: str, language: str = "english") -> str:
    rows = _open_for(client)
    if not rows:
        return f"Error: {client} has no unpaid invoice."
    amt = sum(r["amount"] for r in rows)
    biz = os.getenv("BUSINESS_NAME") or "our team"
    name = rows[0]["client"]
    if (language or "").lower() == "hinglish":
        msg = (f"Namaste {name} ji, {biz} ki taraf se ek chhota reminder: aapka {inr(amt)} ka payment abhi pending hai. "
               "Jab aapko suvidha ho tab bhej dijiye. Kuch poochna ho toh bataiye. Dhanyavaad!")
    else:
        msg = (f"Hello {name}, a gentle reminder from {biz}: a payment of {inr(amt)} is still pending. "
               "Please let us know when we can expect it, or if you need anything from us. Thank you!")
    return f"Here is a draft to copy (I have not sent it): {msg}"
