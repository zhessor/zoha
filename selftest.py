#!/usr/bin/env python3
"""
Zoha self-test — checks every Windows-specific part on THIS PC and writes data/selftest.json.

    python selftest.py

Close Zoha first. Takes ~1 minute. Opens and closes a browser window, plays nothing,
changes nothing (volume/media are only READ, never changed).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

RESULTS = {}


def check(name):
    def deco(fn):
        t = time.time()
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e} | {traceback.format_exc(limit=2).splitlines()[-1]}"
        RESULTS[name] = {"ok": ok, "detail": detail, "seconds": round(time.time() - t, 2)}
        print(f"  [{'ok' if ok else '!!'}] {name}: {str(detail)[:160]}", flush=True)
        return fn
    return deco


print("\nZoha self-test\n-------------")
WIN = sys.platform == "win32"


@check("python + packages")
def _():
    mods = ["numpy", "sounddevice", "faster_whisper", "ctranslate2", "onnxruntime", "av", "PySide6", "playwright",
            "kokoro_onnx", "psutil", "google.genai", "aiohttp", "dotenv"]
    missing = []
    for m in mods:
        try:
            __import__(m)
        except Exception:
            missing.append(m)
    return not missing, f"Python {sys.version.split()[0]}; missing: {missing or 'none'}"


@check("windows media session (play/pause control)")
def _():
    if not WIN:
        return False, "not Windows"
    from zoha.tools import _MEDIA_PS

    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _MEDIA_PS],
                       capture_output=True, text=True, timeout=25, env={**os.environ, "ZOHA_MEDIA_ACTION": "status"},
                       creationflags=0x08000000)
    out = (r.stdout or "").strip()
    line = next((l for l in out.splitlines() if l.strip().startswith("{")), "")
    if line:
        return True, json.loads(line)
    return False, f"no JSON. stdout={out[-300:]!r} stderr={(r.stderr or '')[-400:]!r}"


@check("open windows list (awareness)")
def _():
    from zoha.tools import visible_windows

    w = visible_windows()
    return (len(w) > 0 or not WIN), f"{len(w)} windows: {[t for t, _ in w[:6]]}"


@check("start-menu app index")
def _():
    from zoha.tools import APPS

    APPS._ready.wait(40)
    found = {q: (APPS.find(q) or [None])[0] for q in ("calculator", "chrome", "vs code", "spotify", "whatsapp", "notepad")}
    return len(APPS.apps) > 20, f"{len(APPS.apps)} apps; lookups: {found}"


@check("global hotkey Ctrl+Alt+Z")
def _():
    if not WIN:
        return False, "not Windows"
    import ctypes

    u = ctypes.windll.user32
    ok = bool(u.RegisterHotKey(None, 0x5A1, 0x1 | 0x2 | 0x4000, 0x5A))
    if ok:
        u.UnregisterHotKey(None, 0x5A1)
        return True, "registered and released"
    return False, f"RegisterHotKey failed (error {ctypes.GetLastError()}) – another app may own Ctrl+Alt+Z"


@check("dark title bar")
def _():
    if not WIN:
        return False, "not Windows"
    import ctypes
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication(sys.argv)
    w = QWidget()
    w.show()
    hwnd = int(w.winId())
    on = ctypes.c_int(1)
    hr1 = ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)
    col = ctypes.c_uint(0x0015170F)
    hr2 = ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(col), 4)
    w.close()
    return hr1 == 0, f"dark mode HRESULT={hr1}, caption colour HRESULT={hr2} (non-zero colour = Windows 10, fine)"


@check("zoha's browser (Playwright)")
def _():
    from zoha.browser import get_browser

    b = get_browser()
    snap = b.open("https://example.com")
    chan = b.used_channel
    look_ok = False
    try:
        img, _ = b.look()
        look_ok = len(img) > 1000
    except Exception:
        pass
    b.close()
    return "Example Domain" in snap, f"channel={chan}; page loaded={'Example Domain' in snap}; screenshot-with-labels={look_ok}"


@check("local voice (Kokoro)")
def _():
    from zoha.config import load_settings
    from zoha.local_tts import KokoroVoice

    s = load_settings()
    k = KokoroVoice()
    if not k.load(lambda m: print("      ", m)):
        return False, k.error
    t = time.time()
    pcm = k.synth("Self test complete.", s.kokoro_voice, s.kokoro_speed)
    return pcm is not None and len(pcm) > 1000, f"voice={s.kokoro_voice}; 1.3 s of speech made in {time.time() - t:.2f}s"


@check("speech recognition on GPU")
def _():
    from zoha.config import DATA_DIR

    p = DATA_DIR / "gpu_probe.json"
    data = json.loads(p.read_text()) if p.exists() else {}
    return any(v.get("ok") for v in data.values()), data or "no GPU test recorded yet (Zoha runs it on first launch)"


@check("local brain (Ollama)")
def _():
    from zoha.config import load_settings
    from zoha import local_llm as L

    s = load_settings()
    if not L.server_up(s.local_llm_url):
        if not (L.find_ollama() and L.start_server(s.local_llm_url)):
            return False, "Ollama not running/installed"
    models = L.installed_models(s.local_llm_url)
    ok, name = L.ensure_ready(s.local_llm_url, s.local_llm_model, s.local_llm_ctx, lambda m: print("      ", m))
    if not ok:
        return False, name
    t = time.time()
    L.warm_up(s.local_llm_url, name)
    share = L.gpu_share(s.local_llm_url, name)
    caps = L.model_caps(s.local_llm_url, name)
    return (share or 0) >= 0.9, {"model": name, "on_gpu": f"{(share or 0):.0%}", "capabilities": caps,
                                 "load_s": round(time.time() - t, 1), "installed": models}


@check("microphones")
def _():
    from zoha.audio import list_input_devices

    d = list_input_devices()
    return bool(d), [f"[{i}] {n}{' (default)' if df else ''}" for i, n, df in d]


ok = sum(r["ok"] for r in RESULTS.values())
print(f"\n{ok}/{len(RESULTS)} checks passed")
from zoha.config import DATA_DIR  # noqa: E402

DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "selftest.json").write_text(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M"), "results": RESULTS},
                                                   indent=1, default=str), encoding="utf-8")
print(f"Saved {DATA_DIR / 'selftest.json'} – tell Claude it's done.")
os._exit(0)
