import importlib.util

from zoha import tools as T


def load(name):
    spec = importlib.util.spec_from_file_location(name, T.SKILLS_DIR.parent / "plugins" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_units():
    u = load("unit_converter")
    assert abs(u.convert(5, "km", "miles") - 3.10686) < 1e-4
    assert abs(u.convert(70, "kilos", "pounds") - 154.3236) < 1e-3
    assert abs(u.convert(98.6, "F", "C") - 37.0) < 1e-6 and abs(u.convert(0, "c", "k") - 273.15) < 1e-9


def test_units_reject_mixed_and_unknown():
    u = load("unit_converter")
    assert u.convert_units(5, "km", "kg").startswith("Error") and u.convert_units(5, "parsec", "m").startswith("Error")


def test_pomodoro_schedules_focus_then_break(monkeypatch):
    p = load("pomodoro")
    calls = []
    monkeypatch.setattr(T.CTX, "schedule", lambda d, l, k: calls.append((d, l)) or "ok")
    assert "25 minutes" in p.start_pomodoro()
    assert calls == [(1500.0, "focus session"), (1800.0, "break")]
    calls.clear()
    p.start_pomodoro(9999, 0)           # clamped
    assert calls[0][0] == 180 * 60
