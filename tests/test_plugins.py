"""Community plugins: files dropped into plugins/ add tools, and a broken plugin never stops startup."""
from zoha import plugins
from zoha import tools as T


def test_bundled_example_plugin_registers_its_tools():
    plugins.load_all()
    assert "coin_flip" in T.REGISTRY and "roll_dice" in T.REGISTRY
    assert T.REGISTRY["coin_flip"].fn() in ("Heads", "Tails")
    out = T.REGISTRY["roll_dice"].fn(count=3, sides=6)
    assert out.startswith("Rolled [") and "total" in out


def test_dice_arguments_are_clamped():
    out = T.REGISTRY["roll_dice"].fn(count=999, sides=1)
    assert out.count(",") <= 10          # at most 10 dice, at least 2 sides


def test_broken_plugin_is_skipped(tmp_path, monkeypatch):
    (tmp_path / "good.py").write_text(
        "from zoha.tools import tool\n"
        "@tool('test_hello', 'say hello', 'Hello', 'x')\n"
        "def test_hello():\n    return 'hi'\n")
    (tmp_path / "bad.py").write_text("raise RuntimeError('boom')\n")
    (tmp_path / "_draft.py").write_text("raise RuntimeError('should never load')\n")
    monkeypatch.setattr(plugins, "FOLDER", tmp_path)
    monkeypatch.setattr(plugins, "LOADED", [])
    loaded = plugins.load_all()
    assert loaded == ["good"]
    assert T.REGISTRY["test_hello"].fn() == "hi"
    T.REGISTRY.pop("test_hello", None)
