"""The desktop UI should import and build headless (skipped when PySide6 isn't installed)."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_ui_modules_import():
    import gui
    from zoha.ui import settings_dialog, theme, widgets

    assert theme.TEAL.startswith("#")
    assert hasattr(widgets, "Orb") and hasattr(settings_dialog, "SettingsDialog")
    assert hasattr(gui, "MainWindow") and hasattr(gui, "main")
