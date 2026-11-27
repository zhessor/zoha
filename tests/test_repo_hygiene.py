"""Guards for an open-source repo: no secrets, no personal data, no leftovers from the old name."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEXT = {".py", ".md", ".txt", ".example", ".ipynb", ".json", ".toml", ".yml", ".yaml", ".ps1"}
SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "templates", "data", "models", "node_modules", ".pytest_cache"}


def _files():
    for p in ROOT.rglob("*"):
        if not p.is_file() or set(p.relative_to(ROOT).parts) & SKIP_DIRS:
            continue
        if p.suffix.lower() in TEXT or p.name in (".env.example", ".gitignore"):
            yield p


def _grep(rx):
    hits = []
    for p in _files():
        if p.name == "test_repo_hygiene.py":
            continue
        try:
            t = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if re.search(rx, t):
            hits.append(str(p.relative_to(ROOT)))
    return hits


def test_no_api_keys_in_the_repo():
    assert _grep(r"AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9\-_]{30,}") == []


def test_env_example_has_no_filled_in_secrets():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("GEMINI_API_KEY", "LLM_API_KEY", "SITE_API_KEY"):
        m = re.search(rf"^{key}=(.*)$", text, re.M)
        assert m is not None and m.group(1).strip() in ("", "your_key_here") or "your" in m.group(1)


def test_no_leftovers_from_the_old_name():
    assert _grep(r"(?i)\bzia\b|zia_|_zia\b") == []


def test_no_personal_paths_or_names():
    assert _grep(r"C:\\Users\\athar|D:\\learning|D:\\Zhessor|Atharva") == []


def test_no_env_file_is_committed():
    assert not (ROOT / ".env").exists() or ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8")
