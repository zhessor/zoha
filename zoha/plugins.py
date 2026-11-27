"""
Community plugins: drop a .py file into the `plugins/` folder (next to main.py) and Zoha loads it at start.

A plugin adds tools with the same decorator Zoha's own tools use:

    from zoha.tools import tool

    @tool("coin_flip", "Flip a coin when the user asks for heads or tails.", "Flipping a coin", "🪙")
    def coin_flip() -> str:
        import random
        return random.choice(["Heads", "Tails"])

Files starting with "_" are skipped. A plugin that fails to import is logged and skipped,
so one broken plugin never stops Zoha from starting.
"""

from __future__ import annotations

import importlib.util
import logging
import pathlib

log = logging.getLogger("zoha.plugins")
FOLDER = pathlib.Path(__file__).resolve().parent.parent / "plugins"
LOADED: list = []


def load_all() -> list:
    if not FOLDER.is_dir():
        return LOADED
    for f in sorted(FOLDER.glob("*.py")):
        if f.name.startswith("_") or f.stem in LOADED:
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"zoha_plugin_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            LOADED.append(f.stem)
            log.info("plugin loaded: %s", f.stem)
        except Exception as e:  # noqa: BLE001
            log.warning("plugin %s skipped: %s", f.stem, e)
    return LOADED
