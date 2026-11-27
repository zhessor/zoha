"""
Local brain bootstrap (Ollama).

ensure_ready():
  1. Ollama server reachable?  If not, and Ollama is installed, start `ollama serve`
     (with flash-attention + 8-bit KV cache so the model fits next to Whisper on an 8 GB GPU).
  2. Base model present?  If not, pull it (progress reported).
  3. Create "zoha-<model>" with a larger context window (Ollama's default context is too
     small for Zoha's 40 tools + browser page snapshots). Returns the model name to use.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from typing import Callable, Optional, Tuple

log = logging.getLogger("zoha.local_llm")
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
DETACHED = 0x00000008 if sys.platform == "win32" else 0


def _root(url: str) -> str:
    u = url.rstrip("/")
    return u[:-3] if u.endswith("/v1") else u


def _get(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def _post_stream(url: str, body: dict, timeout: float = 3600):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            line = line.strip()
            if line:
                yield json.loads(line)


def server_up(url: str) -> bool:
    try:
        _get(_root(url) + "/api/tags", 2.0)
        return True
    except Exception:
        return False


def find_ollama() -> Optional[str]:
    exe = shutil.which("ollama")
    if exe:
        return exe
    for p in (os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
              os.path.expandvars(r"%ProgramFiles%\Ollama\ollama.exe"),
              "/usr/local/bin/ollama", "/usr/bin/ollama"):
        if p and os.path.isfile(p):
            return p
    return None


def start_server(url: str) -> bool:
    exe = find_ollama()
    if not exe:
        return False
    env = {**os.environ, "OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_KEEP_ALIVE": "30m"}
    try:
        subprocess.Popen([exe, "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=NO_WINDOW | DETACHED, close_fds=True)
    except Exception as e:
        log.warning("Couldn't start Ollama: %s", e)
        return False
    for _ in range(40):
        time.sleep(0.5)
        if server_up(url):
            return True
    return False


def installed_models(url: str):
    try:
        return [m.get("name", "") for m in _get(_root(url) + "/api/tags").get("models", [])]
    except Exception:
        return []


def _has(models, name: str) -> bool:
    want = name if ":" in name else name + ":latest"
    return any(m == name or m == want for m in models)


def ensure_ready(url: str, model: str, num_ctx: int = 12288,
                 progress: Callable[[str], None] = lambda m: None) -> Tuple[bool, str]:
    """Returns (ok, model_name_to_use | human error message)."""
    if not server_up(url):
        if find_ollama():
            progress("Starting the local AI engine (Ollama)…")
            if not start_server(url):
                return False, "Ollama is installed but didn't start. Open the Ollama app once, then restart Zoha."
        else:
            return False, ("Ollama isn't installed, so the local brain can't run yet. Install it with "
                           "“winget install Ollama.Ollama” (or ollama.com/download), then restart Zoha — "
                           "she downloads the model herself.")
    models = installed_models(url)
    if not _has(models, model):
        progress(f"Downloading the local brain {model} (one time, a few GB)…")
        last = -1
        try:
            for ev in _post_stream(_root(url) + "/api/pull", {"model": model}):
                if ev.get("error"):
                    return False, f"Couldn't download {model}: {ev['error']}"
                tot, done = ev.get("total"), ev.get("completed")
                if tot and done:
                    pct = int(done * 100 / tot)
                    if pct // 10 != last:
                        last = pct // 10
                        progress(f"Downloading {model}: {pct}% of {tot / 1e9:.1f} GB")
        except Exception as e:
            return False, f"Couldn't download {model}: {e}"
        models = installed_models(url)
        if not _has(models, model):
            return False, f"{model} still isn't available after downloading."

    tuned = "zoha-" + model.replace(":", "-").replace("/", "-")
    if not _has(installed_models(url), tuned):
        try:
            for ev in _post_stream(_root(url) + "/api/create",
                                   {"model": tuned, "from": model, "parameters": {"num_ctx": int(num_ctx)}}, timeout=300):
                if ev.get("error"):
                    raise RuntimeError(ev["error"])
            log.info("Created %s (num_ctx=%d)", tuned, num_ctx)
        except Exception as e:
            log.warning("Couldn't create tuned model (%s) – using %s with default context", e, model)
            return True, model
    return True, tuned


def warm_up(url: str, model: str):
    """Load the model into GPU memory now so the first answer isn't slow."""
    try:
        req = urllib.request.Request(_root(url) + "/api/generate",
                                     data=json.dumps({"model": model, "prompt": "", "keep_alive": "30m"}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=180).read()
    except Exception as e:
        log.debug("warm-up failed: %s", e)


def gpu_share(url: str, model: str) -> Optional[float]:
    """Fraction of the loaded model that sits in GPU memory (from /api/ps). None if unknown."""
    try:
        for m in _get(_root(url) + "/api/ps").get("models", []):
            if m.get("name", "").split(":")[0] == model.split(":")[0] or m.get("model") == model:
                size, vram = m.get("size") or 0, m.get("size_vram") or 0
                return (vram / size) if size else None
    except Exception:
        pass
    return None


# Tags that always reason at length before answering (ignore "thinking off") → slow & verbose for a voice assistant
THINKING_ONLY = {"qwen3:4b": "qwen3:4b-instruct", "qwen3:30b": "qwen3:30b-instruct", "qwen3:4b-thinking": "qwen3:4b-instruct"}


def recommended(model: str) -> str:
    """Swap a thinking-only tag for its instruct sibling (same size, answers directly)."""
    m = model.strip()
    if m in THINKING_ONLY:
        return THINKING_ONLY[m]
    if "thinking" in m:
        return m.replace("thinking", "instruct")
    return m


def model_caps(url: str, model: str) -> list:
    try:
        req = urllib.request.Request(_root(url) + "/api/show", data=json.dumps({"model": model}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode()).get("capabilities") or []
    except Exception:
        return []
