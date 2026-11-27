"""
Kokoro — fully local neural voice (82M-parameter model, runs on CPU via onnxruntime).

First run downloads the model (~350 MB) into data/tts/. After that: no internet,
no limits. Works with kokoro-onnx 0.4.x (the version pip installs on Python 3.14)
and 0.6.x — a small shim makes the model inputs match whatever the model file expects.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .config import DATA_DIR

log = logging.getLogger("zoha.kokoro")

MODEL_DIR = DATA_DIR / "tts"
BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"
FILES = {"kokoro-v1.0.onnx": 300_000_000, "voices-v1.0.bin": 25_000_000}  # name → minimum sane size

# Best-sounding voices (Kokoro v1.0). Prefix → language for the phonemizer.
VOICES = [
    ("af_heart", "Heart (US, warm)"), ("af_bella", "Bella (US, bright)"), ("af_nicole", "Nicole (US, soft)"),
    ("af_sarah", "Sarah (US)"), ("af_sky", "Sky (US, young)"), ("af_nova", "Nova (US)"),
    ("bf_emma", "Emma (UK)"), ("bf_isabella", "Isabella (UK)"), ("bf_alice", "Alice (UK)"), ("bf_lily", "Lily (UK)"),
    ("hf_alpha", "Alpha (Hindi)"), ("hf_beta", "Beta (Hindi)"),
    ("am_michael", "Michael (US, male)"), ("am_fenrir", "Fenrir (US, male)"), ("bm_george", "George (UK, male)"),
    ("bm_fable", "Fable (UK, male)"), ("hm_omega", "Omega (Hindi, male)"),
]
LANG = {"a": "en-us", "b": "en-gb", "h": "hi", "e": "es", "f": "fr-fr", "i": "it", "j": "ja", "p": "pt-br", "z": "cmn"}


def models_present() -> bool:
    return all((MODEL_DIR / f).exists() and (MODEL_DIR / f).stat().st_size >= n for f, n in FILES.items())


def download_models(progress: Callable[[str], None] = lambda m: None):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, min_size in FILES.items():
        dest = MODEL_DIR / name
        if dest.exists() and dest.stat().st_size >= min_size:
            continue
        tmp = dest.with_suffix(dest.suffix + ".part")
        req = urllib.request.Request(BASE + name, headers={"User-Agent": "Zoha/2"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done, last = 0, -1
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                pct = int(done * 100 / total) if total else 0
                if total and pct // 20 != last:
                    last = pct // 20
                    progress(f"Downloading Zoha's local voice: {name} {pct}% ({done / 1e6:.0f}/{total / 1e6:.0f} MB)")
        if tmp.stat().st_size < min_size:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"Download of {name} looks incomplete")
        tmp.replace(dest)


class KokoroVoice:
    def __init__(self):
        self.k = None
        self._lock = threading.Lock()
        self._speed = [1.0]
        self.error: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self.k is not None

    def load(self, progress: Callable[[str], None] = lambda m: None) -> bool:
        if self.k is not None:
            return True
        try:
            import kokoro_onnx  # noqa: F401
        except Exception as e:
            self.error = f"kokoro-onnx not installed ({e}) – run: pip install kokoro-onnx"
            log.warning(self.error)
            return False
        try:
            if not models_present():
                progress("Getting Zoha's local voice ready (one-time ~350 MB download)…")
                download_models(progress)
            from kokoro_onnx import Kokoro

            t = time.time()
            k = Kokoro(str(MODEL_DIR / "kokoro-v1.0.onnx"), str(MODEL_DIR / "voices-v1.0.bin"))
            self._patch(k)
            k.create("Ready.", voice="af_heart", speed=1.0, lang="en-us")  # warm-up
            self.k = k
            log.info("Kokoro voice ready in %.1fs", time.time() - t)
            return True
        except Exception as e:
            self.error = f"Local voice failed to load: {e}"
            log.exception(self.error)
            return False

    def _patch(self, k):
        """Make every model input match the dtype the .onnx file declares (fixes kokoro-onnx 0.4.x + v1.1 model)."""
        types = {i.name: i.type for i in k.sess.get_inputs()}
        orig = k.sess.run
        speed = self._speed

        def run(out, feed, *a, **kw):
            feed = dict(feed)
            for n, v in feed.items():
                t = types.get(n)
                if n == "speed":
                    feed[n] = np.array([speed[0]], dtype=np.float32 if t == "tensor(float)" else np.int32)
                elif t == "tensor(float)":
                    feed[n] = np.asarray(v, dtype=np.float32)
                elif t == "tensor(int64)":
                    feed[n] = np.asarray(v, dtype=np.int64)
            return orig(out, feed, *a, **kw)

        k.sess.run = run

    def voices(self):
        try:
            return sorted(self.k.get_voices()) if self.k else [v for v, _ in VOICES]
        except Exception:
            return [v for v, _ in VOICES]

    def synth(self, text: str, voice: str = "af_heart", speed: float = 1.0) -> Optional[np.ndarray]:
        """Returns float32 mono PCM at 24 kHz."""
        if self.k is None:
            return None
        lang = LANG.get(voice[:1], "en-us")
        with self._lock:
            self._speed[0] = float(speed)
            samples, sr = self.k.create(text, voice=voice, speed=float(speed), lang=lang)
        pcm = np.asarray(samples, dtype=np.float32).reshape(-1)
        if sr != 24000:
            from .audio import _resample

            pcm = _resample(pcm, sr, 24000)
        return pcm
