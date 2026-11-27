"""
Speech-to-text with faster-whisper.

- Picks the best model for the hardware: on an NVIDIA GPU (e.g. RTX 5060) it runs
  large-v3-turbo in float16; on CPU it uses small.en int8. Falls back to CPU
  automatically if CUDA/cuDNN is missing or the GPU kernel fails.
- Wake-word pass uses a tiny model on CPU (fast), the command is re-transcribed
  with the main model for accuracy.
- Hallucination filtering (no_speech_prob / logprob / compression ratio and the
  classic Whisper phantom phrases like "Thank you." on silence).
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import warnings
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

log = logging.getLogger("zoha.stt")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("CUDA_CACHE_MAXSIZE", str(4 * 1024 ** 3))  # keep JIT-compiled RTX 50 kernels between runs
warnings.filterwarnings("ignore", module="huggingface_hub")

PHANTOMS = {
    "thank you", "thank you.", "thanks for watching", "thanks for watching!", "you", "bye", "bye.",
    "thank you so much", "subscribe", "please subscribe", "thank you very much", ".", "okay.",
    "so", "uh", "um", "hmm", "mm", "oh", "the end", "music", "[music]", "(music)", "[blank_audio]",
}


def _add_cuda_dll_dirs():
    """On Windows, pip-installed nvidia-cublas/cudnn wheels put DLLs in site-packages/nvidia/*/bin."""
    if sys.platform != "win32":
        return
    for base in sys.path:
        for d in glob.glob(os.path.join(base, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            except Exception:
                pass


def _cudnn_present() -> bool:
    """cuDNN 9 must be loadable, otherwise CTranslate2 can abort the whole process on Windows."""
    if sys.platform == "win32":
        names = ("cudnn_ops64_9.dll", "cudnn64_9.dll")
        dirs = os.environ.get("PATH", "").split(os.pathsep)
        for base in sys.path:
            dirs += glob.glob(os.path.join(base, "nvidia", "*", "bin"))
        return any(os.path.isfile(os.path.join(d, n)) for d in dirs if d for n in names)
    import ctypes

    for lib in ("libcudnn_ops.so.9", "libcudnn.so.9"):
        try:
            ctypes.CDLL(lib)
            return True
        except OSError:
            continue
    return False


def cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0 and _cudnn_present()
    except Exception:
        return False


@dataclass
class Transcript:
    text: str
    confidence: float  # 0..1 (exp of mean logprob)
    seconds: float


PROBE_FILE = None  # set lazily (data/gpu_probe.json)


def _probe_path():
    from .config import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "gpu_probe.json"


def _probe_key(model: str, compute: str) -> str:
    try:
        import ctranslate2

        v = ctranslate2.__version__
    except Exception:
        v = "?"
    return f"ct2={v}|{model}|{compute}"


def cached_probe(model: str, compute: str) -> Optional[dict]:
    try:
        return json.loads(_probe_path().read_text()).get(_probe_key(model, compute))
    except Exception:
        return None


def run_gpu_probe(model: str, compute: str, timeout: float = 480) -> dict:
    """Test the GPU in a separate process (hang/crash safe). Result is cached per CTranslate2 version."""
    from .config import ROOT

    t = time.time()
    try:
        r = subprocess.run([sys.executable, "-m", "zoha.gpu_probe", model, compute], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=0x08000000 if sys.platform == "win32" else 0)
        line = next((l for l in (r.stdout or "").splitlines() if l.startswith("ZOHA_PROBE ")), None)
        res = json.loads(line[10:]) if line else {"ok": False, "error": f"probe exited {r.returncode}: {(r.stderr or '')[-300:]}"}
    except subprocess.TimeoutExpired:
        res = {"ok": False, "error": f"GPU didn't finish a test transcription within {int(timeout)}s"}
    except Exception as e:
        res = {"ok": False, "error": str(e)}
    res["took"] = round(time.time() - t, 1)
    res["when"] = time.strftime("%Y-%m-%d %H:%M")
    try:
        p = _probe_path()
        data = json.loads(p.read_text()) if p.exists() else {}
        data[_probe_key(model, compute)] = res
        p.write_text(json.dumps(data, indent=2))
    except Exception:
        pass
    return res


class Transcriber:
    """
    Device policy (WHISPER_DEVICE=auto):
      GPU proven good before  → load on GPU straight away
      GPU proven bad before   → CPU, no retry (until CTranslate2 is upgraded)
      GPU never tested        → start on CPU immediately, test the GPU in a background
                                subprocess, and hot-swap to it if it passes
    """

    def __init__(self, settings, on_status: Optional[Callable[[str], None]] = None,
                 on_change: Optional[Callable[[], None]] = None):
        _add_cuda_dll_dirs()
        self.s = settings
        self.on_status = on_status or (lambda m: log.info(m))
        self.on_change = on_change or (lambda: None)
        self._lock = threading.Lock()
        self.language = None if settings.stt_language in ("", "auto") else settings.stt_language
        self.gpu_status = "not used"

        want = settings.whisper_device
        gpu_model = self._model_for("cuda")
        gpu_compute = settings.whisper_compute_type if settings.whisper_compute_type != "auto" else "float16"
        has_gpu = want != "cpu" and cuda_available()

        if has_gpu:
            cached = cached_probe(gpu_model, gpu_compute)
            if cached and cached.get("ok"):
                if self._try_gpu(gpu_model, gpu_compute):
                    return
            elif cached and not cached.get("ok"):
                self.gpu_status = f"GPU skipped (earlier test failed: {cached.get('error', '')[:120]})"
                log.warning(self.gpu_status)
            else:
                self._load_cpu()
                self.gpu_status = "testing GPU…"
                threading.Thread(target=self._probe_and_upgrade, args=(gpu_model, gpu_compute),
                                 daemon=True, name="zoha-gpu-probe").start()
                return
        self._load_cpu()

    # ── loading ───────────────────────────────────────────────────────
    def _model_for(self, device: str) -> str:
        name = self.s.whisper_model
        if name == "auto":
            if device == "cuda":
                name = "large-v3-turbo"
            else:
                name = "small.en" if self.language == "en" else "small"
        if self.language not in (None, "en") and name.endswith(".en"):
            name = name[:-3]
        return name

    def _new(self, name, device, compute):
        from faster_whisper import WhisperModel

        t = time.time()
        m = WhisperModel(name, device=device, compute_type=compute, cpu_threads=max(2, (os.cpu_count() or 4) // 2))
        if device == "cuda":
            segs, _ = m.transcribe(np.zeros(16000, np.float32), beam_size=1, language="en", max_new_tokens=4,
                                   without_timestamps=True, vad_filter=False)
            list(segs)
        log.info("Loaded Whisper '%s' on %s/%s in %.1fs", name, device, compute, time.time() - t)
        return m

    def _load_cpu(self):
        self.device, self.compute = "cpu", "int8" if self.s.whisper_compute_type in ("auto", "float16") else self.s.whisper_compute_type
        self.model_name = self._model_for("cpu")
        self.model = self._new(self.model_name, "cpu", self.compute)
        wname = self.s.wake_model if self.s.wake_model != "auto" else "tiny.en"
        if wname == self.model_name:
            self.wake, self.wake_model_name = self.model, wname
        else:
            self.wake, self.wake_model_name = self._new(wname, "cpu", "int8"), wname

    def _try_gpu(self, name, compute) -> bool:
        try:
            model = self._new(name, "cuda", compute)
        except Exception as e:
            self.gpu_status = f"GPU failed: {e}"
            log.warning("%s – using CPU", self.gpu_status)
            return False
        with self._lock:
            self.model, self.model_name, self.device, self.compute = model, name, "cuda", compute
            if self.s.wake_model == "auto":
                self.wake, self.wake_model_name = model, name  # GPU is fast enough for the wake pass too
        self.gpu_status = "GPU active"
        return True

    def _probe_and_upgrade(self, name, compute):
        self.on_status("Testing your GPU for faster, more accurate recognition (first time only; "
                       "an RTX 50-series card may need a few minutes). Zoha already works on CPU meanwhile.")
        res = run_gpu_probe(name, compute)
        log.info("GPU probe: %s", res)
        if not res.get("ok"):
            self.gpu_status = f"GPU test failed: {res.get('error', 'unknown')}"
            self.on_status(f"Staying on CPU – {self.gpu_status[:200]}")
            return
        if self._try_gpu(name, compute):
            self.on_status(f"Switched speech recognition to the GPU ({name}). "
                           f"First test took {res.get('took')}s; next launches start on GPU directly.")
            self.on_change()
        else:
            self.on_status(f"Staying on CPU – {self.gpu_status[:200]}")

    # ------------------------------------------------------------------
    def _run(self, model, audio: np.ndarray, beam: int, prompt: Optional[str], hotwords: Optional[str]) -> Transcript:
        if audio is None or len(audio) < 1600:
            return Transcript("", 0.0, 0.0)
        audio = audio.astype(np.float32)
        peak = float(np.max(np.abs(audio)))
        if 0.0005 < peak < 0.5:
            audio = audio * (0.7 / peak)
        with self._lock:
            segments, info = model.transcribe(
                audio,
                language=self.language,
                beam_size=beam,
                best_of=beam,
                temperature=[0.0, 0.2, 0.4],
                condition_on_previous_text=False,
                without_timestamps=True,
                vad_filter=False,
                initial_prompt=prompt,
                hotwords=hotwords,
                no_speech_threshold=0.6,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4,
            )
            segments = list(segments)
        texts, lps = [], []
        for seg in segments:
            if seg.no_speech_prob > 0.6 and seg.avg_logprob < -0.7:
                continue
            if seg.compression_ratio > 2.6:
                continue
            texts.append(seg.text.strip())
            lps.append(seg.avg_logprob)
        text = " ".join(t for t in texts if t).strip()
        conf = float(np.exp(np.mean(lps))) if lps else 0.0
        if text.lower().strip(" .!?,") in {p.strip(" .!?,") for p in PHANTOMS} and conf < 0.75:
            text = ""
        text = re.sub(r"\s+", " ", text)
        return Transcript(text, conf, len(audio) / 16000)

    def transcribe(self, audio: np.ndarray, context: str = "") -> Transcript:
        """Accurate pass (main model). `context` = vocabulary hint (app names, wake word)."""
        prompt = f"{self.s.assistant_name}. {context}".strip() if context else None
        return self._run(self.model, audio, beam=5, prompt=prompt, hotwords=self.s.assistant_name)


    def quick(self, audio: np.ndarray, bias: bool = True) -> Transcript:
        """Fast pass for wake-word spotting. No prompt → no 'Zoha' hallucinations on noise.
        bias=False while Zoha is speaking: hotwords made Whisper 'hear' “Zoha Jarvis” in her own echo."""
        beam = 1 if self.wake is not self.model else 2
        # standby: hint all wake words (measured: dropping this loses ~7% of wake-ups);
        # while Zoha speaks (bias=False) no hint, so her own echo isn't "heard" as "Zoha Jarvis"
        hot = " ".join(w.title() for w in self.s.all_wake_words()) if bias else None
        return self._run(self.wake, audio, beam=beam, prompt=None, hotwords=hot)

    @property
    def shared(self) -> bool:
        return self.wake is self.model
