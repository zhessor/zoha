"""Publish gate, routines, business desk."""
import importlib.util
import json
import time
import zipfile
import io

import pytest

from zoha import confirm, live_site, routines
from zoha import tools as T
from zoha.config import DATA_DIR


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("zoha.live_site.DATA_DIR", tmp_path)
    monkeypatch.setattr("zoha.routines.DATA_DIR", tmp_path)
    confirm.cancel()
    routines._rec = None
    yield
    confirm.cancel()
    routines._rec = None


def biz():
    spec = importlib.util.spec_from_file_location("biz_desk", T.SKILLS_DIR.parent / "plugins" / "business_desk.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---- confirm gate
def test_confirm_runs_only_on_yes_and_once():
    hits = []
    msg = confirm.request("x", "I will do X.", lambda: hits.append(1) or "done")
    assert msg.startswith("NOT DONE YET") and not hits
    assert confirm.is_yes("yes please") and not confirm.is_yes("yes but change the colour")
    assert confirm.apply() == "done" and hits == [1]
    assert confirm.apply().startswith("Error")      # a second yes does nothing
    assert hits == [1]


def test_confirm_expires(monkeypatch):
    confirm.request("x", "X.", lambda: "done")
    real = time.time()
    monkeypatch.setattr(confirm.time, "time", lambda: real + confirm.WINDOW + 1)
    assert confirm.pending() is None and confirm.apply().startswith("Error")


# ---- publish
def make_page(tmp_path):
    p = tmp_path / "bakery.html"
    p.write_text("<html></html>", encoding="utf-8")
    (tmp_path / "bakery_photos").mkdir()
    (tmp_path / "bakery_photos" / "a.jpg").write_bytes(b"x")
    (tmp_path / "bakery_photos" / "secret.env").write_text("KEY=1")
    return p


def test_zip_contains_only_page_and_its_assets(tmp_path):
    z = zipfile.ZipFile(io.BytesIO(live_site.build_zip(make_page(tmp_path))))
    assert sorted(z.namelist()) == ["bakery_photos/a.jpg", "index.html"]


def test_deploy_creates_then_reuses_site(tmp_path):
    page = make_page(tmp_path)
    calls = []

    def fake(method, path, body, ctype, token):
        calls.append((method, path, ctype))
        return {"id": "s1"} if path == "/sites" else {"ssl_url": "https://x.netlify.app"}

    assert live_site.deploy(page, "tok", call=fake) == "https://x.netlify.app"
    live_site.deploy(page, "tok", call=fake)
    assert [c[1] for c in calls] == ["/sites", "/sites/s1/deploys", "/sites/s1/deploys"]


def test_publish_tool_asks_first_and_never_deploys_itself(tmp_path, monkeypatch):
    page = make_page(tmp_path)
    monkeypatch.setenv("NETLIFY_TOKEN", "tok")
    monkeypatch.setattr(T.CTX, "last_file", page)
    sent = []
    monkeypatch.setattr(live_site, "deploy", lambda p, t, call=None: sent.append(p) or "https://x.netlify.app")
    out = T.call_tool("site_publish", {})
    assert out.startswith("NOT DONE YET") and not sent
    assert "tok" not in out
    assert "live at https://x.netlify.app" in confirm.apply() and sent == [page]


def test_publish_without_token_explains():
    import os
    os.environ.pop("NETLIFY_TOKEN", None)
    assert "NETLIFY_TOKEN" in T.call_tool("site_publish", {})


# ---- routines
def test_routine_records_safe_steps_and_replays(monkeypatch):
    ran = []
    T.REGISTRY["fake_open"] = T.Tool("fake_open", "d", {"type": "object", "properties": {"name": {"type": "string"}}},
                                     lambda name: ran.append(name) or f"Opened {name}", "l", "i")
    try:
        T.call_tool("routine_record", {"name": "Work Mode"})
        T.call_tool("fake_open", {"name": "code"})
        T.call_tool("power", {"action": "shutdown"})        # must never be recorded
        saved = T.call_tool("routine_save", {})
        assert "Saved 'work mode' with 1 steps" in saved and "power" in saved
        ran.clear()
        assert "1 of 1" in T.call_tool("routine_run", {"name": "work mode"})
        assert ran == ["code"]
    finally:
        T.REGISTRY.pop("fake_open", None)


def test_routine_never_allows_risky_tools():
    for n in ("power", "write_file", "site_publish", "routine_run", "site_propose", "browser_click"):
        assert not routines.allowed(n)


# ---- business desk
def test_amounts_and_indian_grouping():
    b = biz()
    assert b.parse_amount("₹45,000") == 45000 and b.parse_amount("1.5 lakh") == 150000 and b.parse_amount("12k") == 12000
    assert b.inr(1234567) == "₹12,34,567" and b.inr(950) == "₹950" and b.inr(45000.5) == "₹45,000.50"


def test_parse_items_and_totals():
    b = biz()
    rows = b.parse_items("Kitchen cabinets 2 at 45000; hob x1 @ 12k")
    assert rows == [("Kitchen cabinets", 2, 45000.0), ("hob", 1, 12000.0)]
    page = b.quote_html("Mr <Shah>", rows, 18, 7)
    assert "₹1,02,000" in page and "₹1,20,360" in page and "&lt;Shah&gt;" in page


def test_unpaid_flow_and_followup_never_sends(tmp_path, monkeypatch):
    b = biz()
    monkeypatch.setattr(b, "DATA_DIR", tmp_path)
    assert "owes ₹30,000" in b.add_invoice("Mr Shah", "30000", "5th")
    assert "Total ₹30,000" in b.list_unpaid()
    assert "not sent" in b.draft_followup("shah", "hinglish").lower() or "have not sent" in b.draft_followup("shah")
    assert "Marked 1" in b.mark_paid("Shah") and "Nobody owes" in b.list_unpaid()
