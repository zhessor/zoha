"""
Audio layer.

AudioHub     – ONE microphone stream for the whole app (no more 3 streams fighting
               over the device). 32 ms frames → Silero VAD → utterance segmenter.
SileroVAD    – streaming neural voice-activity detection (model ships inside
               faster-whisper, so no extra download). Energy VAD fallback.
Player       – one persistent output stream: gapless sentence playback, instant
               interrupt, and a real output level for the GUI orb.
"""

from __future__ import annotations

import collections
import logging
import math
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional

import numpy as np

log = logging.getLogger("zoha.audio")

SAMPLE_RATE = 16000
FRAME = 512  # 32 ms @ 16 kHz (Silero native window)
FRAME_MS = FRAME * 1000 / SAMPLE_RATE


def _sd():
    import sounddevice as sd  # imported lazily so tests run without PortAudio

    return sd


# ──────────────────────────────────────────────────────────────────────────────
# Voice activity detection
# ──────────────────────────────────────────────────────────────────────────────
class SileroVAD:
    """Streaming Silero VAD using the ONNX model bundled with faster-whisper."""

    def __init__(self):
        import onnxruntime as ort
        import faster_whisper

        assets = os.path.join(os.path.dirname(faster_whisper.__file__), "assets")
        candidates = [f for f in os.listdir(assets) if f.startswith("silero") and f.endswith(".onnx")]
        if not candidates:
            raise RuntimeError("Silero VAD model not found in faster-whisper assets")
        path = os.path.join(assets, sorted(candidates)[-1])

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self.session = ort.InferenceSession(path, providers=["CPUExecutionProvider"], sess_options=opts)
        names = {i.name for i in self.session.get_inputs()}
        if {"h", "c"} <= names:
            self.kind = "hc"  # silero v6 export used by faster-whisper >= 1.1
        elif "state" in names:
            self.kind = "state"  # silero v5 official export
        else:
            raise RuntimeError(f"Unknown Silero model signature: {names}")
        self.reset()
        log.info("Silero VAD loaded (%s)", os.path.basename(path))

    def reset(self):
        self._context = np.zeros((1, 64), dtype=np.float32)
        if self.kind == "hc":
            self._h = np.zeros((1, 1, 128), dtype=np.float32)
            self._c = np.zeros((1, 1, 128), dtype=np.float32)
        else:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        x = np.concatenate([self._context, frame.reshape(1, -1).astype(np.float32)], axis=1)
        self._context = x[:, -64:]
        if self.kind == "hc":
            out, self._h, self._c = self.session.run(None, {"input": x, "h": self._h, "c": self._c})
        else:
            out, self._state = self.session.run(
                None, {"input": x, "state": self._state, "sr": np.array(SAMPLE_RATE, dtype=np.int64)}
            )
        return float(np.asarray(out).reshape(-1)[0])


class EnergyVAD:
    """Fallback: adaptive noise-floor energy detector mapped to a 0..1 'probability'."""

    def __init__(self):
        self.floor = 0.003

    def reset(self):
        pass

    def __call__(self, frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(frame ** 2)) + 1e-9)
        ratio = rms / max(self.floor, 1e-4)
        if ratio < 2.0:
            self.floor = 0.97 * self.floor + 0.03 * rms
        return float(min(1.0, max(0.0, (ratio - 1.5) / 2.5)))


def make_vad():
    try:
        return SileroVAD()
    except Exception as e:  # pragma: no cover
        log.warning("Silero VAD unavailable (%s) – falling back to energy VAD", e)
        return EnergyVAD()


# ──────────────────────────────────────────────────────────────────────────────
# Segmenter: frames → utterances
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Utterance:
    audio: np.ndarray
    started: float
    ended: float

    @property
    def seconds(self) -> float:
        return len(self.audio) / SAMPLE_RATE


class Segmenter:
    def __init__(
        self,
        vad,
        threshold: float = 0.5,
        end_silence_ms: int = 700,
        max_seconds: float = 25.0,
        preroll_ms: int = 320,
        min_speech_ms: int = 180,
    ):
        self.vad = vad
        self.on_threshold = threshold
        self.off_threshold = max(0.15, threshold - 0.15)
        self.end_frames = max(3, int(end_silence_ms / FRAME_MS))
        self.max_frames = int(max_seconds * 1000 / FRAME_MS)
        self.min_speech_frames = max(2, int(min_speech_ms / FRAME_MS))
        self.preroll: Deque[np.ndarray] = collections.deque(maxlen=max(2, int(preroll_ms / FRAME_MS)))
        self._reset()

    def _reset(self):
        self.active = False
        self.frames: List[np.ndarray] = []
        self.speech_frames = 0
        self.silence = 0
        self.rising = 0
        self.t0 = 0.0

    def reset(self):
        self._reset()
        self.preroll.clear()
        self.vad.reset()

    def push(self, frame: np.ndarray) -> tuple:
        """Returns (event, payload): ('start', None) | ('end', Utterance) | (None, prob)."""
        p = self.vad(frame)
        if not self.active:
            self.preroll.append(frame)
            self.rising = self.rising + 1 if p >= self.on_threshold else 0
            if self.rising >= 2:
                self.active = True
                self.frames = list(self.preroll)
                self.speech_frames = self.rising
                self.silence = 0
                self.t0 = time.time()
                self.preroll.clear()
                return ("start", p)
            return (None, p)

        self.frames.append(frame)
        if p >= self.off_threshold:
            self.speech_frames += 1
            self.silence = 0
        else:
            self.silence += 1

        if self.silence >= self.end_frames or len(self.frames) >= self.max_frames:
            frames, speech = self.frames, self.speech_frames
            t0 = self.t0
            # trim most of the trailing silence, keep ~160 ms tail
            keep_tail = 5
            if self.silence > keep_tail:
                frames = frames[: len(frames) - (self.silence - keep_tail)]
            self._reset()
            self.vad.reset()
            if speech >= self.min_speech_frames:
                return ("end", Utterance(np.concatenate(frames), t0, time.time()))
            return ("discard", None)
        return (None, p)


# ──────────────────────────────────────────────────────────────────────────────
# Microphone hub
# ──────────────────────────────────────────────────────────────────────────────
class AudioHub:
    """
    Owns the microphone. Callbacks are invoked from the hub's worker thread:
      on_level(float 0..1), on_speech_start(), on_utterance(Utterance)
    """

    def __init__(self, settings, on_level=None, on_speech_start=None, on_utterance=None):
        self.s = settings
        self.on_level = on_level or (lambda lv: None)
        self.on_speech_start = on_speech_start or (lambda: None)
        self.on_utterance = on_utterance or (lambda u: None)
        self.device = settings.audio_device_index
        self.gain = max(0.1, settings.mic_gain)
        self._q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=400)
        self._stream = None
        self._thread: Optional[threading.Thread] = None
        self._run = False
        self.gate = threading.Event()  # set = mic frames are processed
        self.gate.set()
        self.segmenter = Segmenter(
            make_vad(),
            threshold=settings.vad_threshold,
            end_silence_ms=settings.vad_end_silence_ms,
            max_seconds=settings.max_utterance_sec,
        )
        self._lock = threading.Lock()
        self.error: Optional[str] = None

    # --- stream lifecycle -----------------------------------------------------
    def _callback(self, indata, frames, time_info, status):
        try:
            self._q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def start(self):
        with self._lock:
            if self._stream is not None:
                return
            sd = _sd()
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=FRAME,
                device=self.device,
                callback=self._callback,
            )
            self._stream.start()
            self.error = None
        if self._thread is None or not self._thread.is_alive():
            self._run = True
            self._thread = threading.Thread(target=self._worker, name="zoha-mic", daemon=True)
            self._thread.start()
        log.info("Microphone open (device=%s, gain=%.1fx)", self.device if self.device is not None else "default", self.gain)

    def stop(self):
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
        self.segmenter.reset()
        self._drain()

    def shutdown(self):
        self._run = False
        self.stop()

    def set_device(self, index: Optional[int]):
        was_open = self._stream is not None
        self.stop()
        self.device = index
        if was_open:
            self.start()

    @property
    def is_open(self) -> bool:
        return self._stream is not None

    def _drain(self):
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                return

    def flush(self):
        """Drop buffered audio + any half-captured utterance (e.g. after Zoha spoke)."""
        self._drain()
        self.segmenter.reset()

    # --- worker ---------------------------------------------------------------
    def _worker(self):
        last_level = 0.0
        while self._run:
            try:
                frame = self._q.get(timeout=0.2)
            except queue.Empty:
                if self._stream is None:
                    self.on_level(0.0)
                continue
            if len(frame) != FRAME:
                continue
            frame = np.clip(frame * self.gain, -1.0, 1.0)
            rms = float(np.sqrt(np.mean(frame ** 2)))
            level = min(1.0, (20 * math.log10(rms + 1e-6) + 60) / 50)  # -60 dB..-10 dB → 0..1
            last_level = 0.6 * last_level + 0.4 * max(0.0, level)
            self.on_level(last_level)
            if not self.gate.is_set():
                continue
            try:
                event, payload = self.segmenter.push(frame)
            except Exception as e:  # never let VAD kill the mic thread
                log.error("VAD error: %s", e)
                continue
            if event == "start":
                self.on_speech_start()
            elif event == "end":
                self.on_utterance(payload)


def list_input_devices() -> List[tuple]:
    """[(index, name, is_default)] – de-duplicated, preferring the WASAPI/MME host API."""
    try:
        sd = _sd()
        default_in = sd.default.device[0]
        out = []
        seen = set()
        hostapis = sd.query_hostapis()
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) <= 0:
                continue
            api = hostapis[dev["hostapi"]]["name"] if hostapis else ""
            if "WDM-KS" in api:
                continue
            key = dev["name"].split("(")[0].strip().lower()
            if key in seen and idx != default_in:
                continue
            seen.add(key)
            out.append((idx, dev["name"], idx == default_in))
        return out
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Output player
# ──────────────────────────────────────────────────────────────────────────────
class Player:
    """Persistent output stream with a PCM queue. Thread-safe."""

    def __init__(self, sample_rate: int = 24000):
        self.sr = sample_rate
        self._buf = collections.deque()
        self._cur: Optional[np.ndarray] = None
        self._pos = 0
        self._lock = threading.Lock()
        self.level = 0.0
        self._stream = None
        self._idle = threading.Event()
        self._idle.set()
        self.on_level: Callable[[float], None] = lambda lv: None

    def _ensure(self):
        if self._stream is None:
            sd = _sd()
            self._stream = sd.OutputStream(
                samplerate=self.sr, channels=1, dtype="float32", blocksize=1024, callback=self._cb
            )
            self._stream.start()

    def _cb(self, outdata, frames, t, status):
        out = np.zeros(frames, dtype=np.float32)
        filled = 0
        with self._lock:
            while filled < frames:
                if self._cur is None or self._pos >= len(self._cur):
                    if not self._buf:
                        self._cur = None
                        break
                    self._cur = self._buf.popleft()
                    self._pos = 0
                n = min(frames - filled, len(self._cur) - self._pos)
                out[filled : filled + n] = self._cur[self._pos : self._pos + n]
                self._pos += n
                filled += n
            if self._cur is None and not self._buf:
                self._idle.set()
        outdata[:, 0] = out
        rms = float(np.sqrt(np.mean(out ** 2)))
        self.level = 0.5 * self.level + 0.5 * min(1.0, rms * 6)
        try:
            self.on_level(self.level)
        except Exception:
            pass

    def play(self, pcm: np.ndarray, sr: int):
        if pcm is None or len(pcm) == 0:
            return
        if sr != self.sr:
            pcm = _resample(pcm, sr, self.sr)
        try:
            self._ensure()
        except Exception as e:
            if not getattr(self, "_warned", False):
                log.error("No audio output device (%s) – Zoha can't speak until one is available", e)
                self._warned = True
            return
        with self._lock:
            self._idle.clear()
            self._buf.append(pcm.astype(np.float32))

    def stop(self):
        with self._lock:
            self._buf.clear()
            self._cur = None
            self._idle.set()

    @property
    def busy(self) -> bool:
        return not self._idle.is_set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._idle.wait(timeout)

    def close(self):
        self.stop()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None


def _resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or len(x) == 0:
        return x
    n_out = int(round(len(x) * sr_out / sr_in))
    return np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x).astype(np.float32)


# ──────────────────────────────────────────────────────────────────────────────
# Chimes (synthesised, no files)
# ──────────────────────────────────────────────────────────────────────────────
def _tone(freqs, dur, sr=24000, vol=0.22):
    t = np.arange(int(sr * dur)) / sr
    seg = len(t) // len(freqs)
    out = np.zeros_like(t)
    for i, f in enumerate(freqs):
        s = slice(i * seg, (i + 1) * seg if i < len(freqs) - 1 else len(t))
        tt = t[s] - t[s][0]
        env = np.minimum(1.0, tt / 0.008) * np.exp(-tt * 9)
        out[s] = np.sin(2 * np.pi * f * tt) * env + 0.25 * np.sin(4 * np.pi * f * tt) * env
    return (out * vol).astype(np.float32)


CHIME_WAKE = _tone([880, 1318.5], 0.20)
CHIME_DONE = _tone([1318.5, 880], 0.20, vol=0.15)
CHIME_ERROR = _tone([440, 330], 0.24, vol=0.18)
CHIME_ALARM = np.concatenate([_tone([988, 1319, 1568], 0.36), np.zeros(4000, np.float32)] * 3)
