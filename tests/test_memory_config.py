"""Memory persists locally; configuration defaults are generic (no personal values)."""
from zoha.config import load_settings
from zoha.memory import Memory


def test_history_is_trimmed_and_saved(tmp_path):
    p = tmp_path / "memory.json"
    m = Memory(path=p, max_turns=2)
    for i in range(5):
        m.add_turn(f"q{i}", f"a{i}")
    assert len(m.history) == 4                      # 2 turns x (user + assistant)
    again = Memory(path=p, max_turns=2)
    assert [h["text"] for h in again.history][-2:] == ["q4", "a4"]


def test_defaults_are_generic(monkeypatch):
    for k in ("USER_NAME", "HOME_CITY", "WAKE_WORD", "ASSISTANT_NAME"):
        monkeypatch.delenv(k, raising=False)
    s = load_settings()
    assert s.wake_word == "zoha"
    assert s.user_name.lower() in ("there", "friend", "")
