"""Web-page writing: the design kit, the lint rules, and the repair layers."""
import pytest

from zoha import tools as T
from zoha import web3d, web_kit

GOOD = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Iron Works Gym, Andheri East</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head><body><h1>Iron Works Gym</h1></body></html>"""


def test_starter_is_a_full_page():
    html, note = web_kit.build_starter("a gym in Andheri East")
    assert html.lower().startswith("<!doctype html")
    assert "</html>" in html
    assert isinstance(note, str) and note


def test_starter_is_seeded():
    a, _ = web_kit.build_starter("a cafe in Bandra", seed="s1")
    b, _ = web_kit.build_starter("a cafe in Bandra", seed="s1")
    assert a == b


def test_there_are_many_layouts():
    assert web_kit.count_layouts() > 100_000


def test_lint_flags_placeholder_text():
    problems = " ".join(T.lint_html("<html><body><h1>Lorem ipsum</h1><img src=x></body></html>")).lower()
    assert "placeholder" in problems or "lorem" in problems
    assert "alt" in problems


def test_lint_flags_the_starter_placeholders_it_ships_with():
    html, _ = web_kit.build_starter("a gym in Andheri East")
    assert any("placeholder" in p.lower() for p in T.lint_html(html))


def test_autofix_adds_layers_and_strip_removes_them():
    html, _ = web_kit.build_starter("a gym in Andheri East")
    fixed = T.autofix_html(html)
    assert len(fixed) > len(html)
    stripped = T.strip_layers(fixed)
    assert abs(len(stripped) - len(html)) < len(html) * 0.1


@pytest.mark.parametrize("text, theme", [
    ("a gym", "dumbbells"),
])
def test_3d_theme_matches_the_business(text, theme):
    assert web3d.theme_for(text) == theme


def test_3d_theme_has_a_default():
    assert web3d.theme_for("something unusual") == "sculpture"


def test_add_3d_is_idempotent():
    html, _ = web_kit.build_starter("a gym in Andheri East")
    once = web3d.add_3d(html)
    assert web3d.add_3d(once) == once


def test_skill_files_have_a_header_that_is_not_sent_to_the_model():
    from pathlib import Path

    for f in sorted(T.SKILLS_DIR.glob("*.md")):
        raw = f.read_text(encoding="utf-8")
        meta = T.skill_meta(raw)
        assert meta.get("name") == f.stem, f
        assert len(meta.get("description", "")) > 20, f
        body = T.skill_text(raw)
        assert not body.startswith("---") and body.startswith("# Skill"), f


def test_skill_loader_returns_the_body_only():
    text, checklist = T._skill("email", "fallback")
    assert text.startswith("# Skill") and "name: email" not in text
