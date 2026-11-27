"""
Streaming text-to-speech.

The LLM streams text → SentenceChunker cuts it into speakable sentences →
each sentence is synthesised with Edge neural TTS while the previous one plays.
First words come out ~1 s after the model starts answering, and speech can be
interrupted instantly (Esc, click, or saying "Zoha"/"stop").

Offline fallback: Windows SAPI voice via PowerShell.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import subprocess
import sys
import tempfile
from typing import List, Optional

import numpy as np

from .audio import Player

log = logging.getLogger("zoha.tts")

ABBREV = {"mr.", "mrs.", "ms.", "dr.", "st.", "vs.", "e.g.", "i.e.", "etc.", "approx.", "no.", "jr.", "sr.", "inc.", "ltd."}


def speakable(text: str) -> str:
    """Markdown/URLs/symbols → natural spoken text."""
    t = re.sub(r"```[\s\S]*?```", " ", text)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://(?:www\.)?([^/\s]+)\S*", r"\1", t)
    t = re.sub(r"^\s*#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"(\*\*|__)(.+?)\1", r"\2", t)
    t = re.sub(r"(?<!\w)[*_](.+?)[*_](?!\w)", r"\1", t)
    t = re.sub(r"^\s*[-*+•]\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*>\s*", "", t, flags=re.M)
    t = re.sub(r"\|", ", ", t)
    t = t.replace("&", " and ").replace("°C", " degrees").replace("°", " degrees").replace("%", " percent")
    t = t.replace("₹", " rupees ").replace("→", " to ").replace("—", ", ").replace("–", " to ")
    t = re.sub(r"[#*_~<>{}\[\]]", " ", t)
    t = re.sub("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]+", " ", t)  # emojis aren't speech
    return re.sub(r"\s+", " ", t).strip()


def decode_audio_bytes(data, sr: int = 24000) -> np.ndarray:
    """Decode mp3/wav (bytes or path) to mono float32 at `sr` using PyAV (bundled with faster-whisper)."""
    import av

    src = io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data
    chunks = []
    with av.open(src) as container:
        stream = container.streams.audio[0]
        res = av.AudioResampler(format="flt", layout="mono", rate=sr)
        for frame in container.decode(stream):
            for f in res.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        for f in res.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)


class SentenceChunker:
    """Feed streamed text; get back complete sentences (skips fenced code)."""

    def __init__(self, min_chars: int = 28):
        self.buf = ""
        self.min_chars = min_chars
        self.in_code = False
        self.code_announced = False

    def feed(self, delta: str) -> List[str]:
        self.buf += delta
        out: List[str] = []
        while True:
            if self.in_code:
                end = self.buf.find("```")
                if end < 0:
                    return out
                self.buf = self.buf[end + 3 :]
                self.in_code = False
                continue
            start = self.buf.find("```")
            head = self.buf if start < 0 else self.buf[:start]
            cut = self._cut(head, final=start >= 0)
            if cut:
                sent, rest = head[:cut], head[cut:]
                self.buf = rest + ("" if start < 0 else self.buf[start:])
                if sent.strip():
                    out.append(sent.strip())
                continue
            if start >= 0:
                if head.strip():
                    out.append(head.strip())
                self.buf = self.buf[start + 3 :]
                self.in_code = True
                if not self.code_announced:
                    out.append("I've put the code on your screen.")
                    self.code_announced = True
                continue
            return out

    def _cut(self, s: str, final: bool) -> int:
        for m in re.finditer(r"([.!?…]+[\"')\]]*)(\s+)|(\n\s*\n)|(:\s*\n)|(\n(?=\s*[-*•\d]))", s):
            end = m.end()
            piece = s[:end].strip()
            if m.group(1):
                last = piece.split()[-1].lower() if piece.split() else ""
                if last in ABBREV or re.fullmatch(r"\d+\.", last):
                    continue
            if len(piece) >= self.min_chars or m.group(3) or m.group(5):
                return end
        if final:
            return 0
        if len(s) > 220:  # very long clause with no punctuation → cut at a comma
            c = s.rfind(", ", 0, 200)
            if c > 40:
                return c + 2
        return 0

    def flush(self) -> List[str]:
        rest = "" if self.in_code else self.buf.strip()
        self.buf = ""
        return [rest] if rest else []


class Speaker:
    def __init__(self, settings, player: Optional[Player] = None):
        self.s = settings
        self.voice = settings.tts_voice
        self.player = player or Player(24000)
        self._q: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None
        self._gen = 0
        self.speaking = False
        self.edge_ok = True
        from .local_tts import KokoroVoice

        self.kokoro = KokoroVoice()

    def _queue(self) -> asyncio.Queue:
        if self._q is None:
            self._q = asyncio.Queue()
        return self._q

    async def _synth_edge(self, text: str) -> Optional[np.ndarray]:
        import edge_tts

        comm = edge_tts.Communicate(text, self.voice, rate=self.s.tts_rate, pitch=self.s.tts_pitch)
        data = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                data.extend(chunk["data"])
        if not data:
            return None
        return await asyncio.to_thread(decode_audio_bytes, bytes(data), 24000)

    async def _synth_sapi(self, text: str) -> Optional[np.ndarray]:
        if sys.platform != "win32":
            return None
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        script = ("Add-Type -AssemblyName System.Speech;$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                  "$v=$s.GetInstalledVoices()|%{$_.VoiceInfo}|?{$_.Gender -eq 'Female'}|select -First 1;"
                  "if($v){$s.SelectVoice($v.Name)};$s.Rate=1;$s.SetOutputToWaveFile($env:ZOHA_WAV);$s.Speak($env:ZOHA_TXT);$s.Dispose()")
        try:
            await asyncio.to_thread(
                subprocess.run, ["powershell", "-NoProfile", "-Command", script],
                env={**os.environ, "ZOHA_WAV": path, "ZOHA_TXT": text}, capture_output=True, timeout=60,
                creationflags=0x08000000,
            )
            return await asyncio.to_thread(decode_audio_bytes, path, 24000)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def prepare(self, progress=lambda m: None) -> str:
        """Load the local voice (downloads it once). Returns a short status."""
        if self.s.tts_engine == "kokoro":
            return "local voice ready" if self.kokoro.load(progress) else (self.kokoro.error or "local voice unavailable")
        return "online voice"

    async def synth(self, text: str) -> Optional[np.ndarray]:
        text = speakable(text)
        if not text:
            return None
        if self.s.tts_engine == "kokoro":
            if self.kokoro.ready:
                try:
                    return await asyncio.to_thread(self.kokoro.synth, text, self.s.kokoro_voice, self.s.kokoro_speed)
                except Exception as e:
                    log.warning("Kokoro failed (%s) – using Windows voice", e)
            return await self._synth_sapi(text)  # stays fully local
        if self.edge_ok:
            for attempt in range(2):
                try:
                    return await asyncio.wait_for(self._synth_edge(text), timeout=15)
                except Exception as e:
                    log.warning("Edge TTS failed (%s)%s", e, " – retrying" if attempt == 0 else " – using offline voice")
            self.edge_ok = False
            asyncio.get_running_loop().call_later(120, lambda: setattr(self, "edge_ok", True))
        if self.kokoro.ready:
            try:
                return await asyncio.to_thread(self.kokoro.synth, text, self.s.kokoro_voice, self.s.kokoro_speed)
            except Exception:
                pass
        return await self._synth_sapi(text)

    # ── streaming API ─────────────────────────────────────────────────────
    def say(self, sentence: str):
        """Queue a sentence (non-blocking). Starts the pipeline if idle."""
        self._queue().put_nowait((self._gen, sentence))
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._pump())

    async def _pump(self):
        q = self._queue()
        self.speaking = True
        pending: Optional[asyncio.Task] = None
        pending_gen = -1
        try:
            while True:
                if pending is None:
                    try:
                        gen, text = q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if gen != self._gen:
                        continue
                    pending, pending_gen = asyncio.ensure_future(self.synth(text)), gen
                pcm = await pending
                this_gen, pending = pending_gen, None
                # start synthesising the next sentence while this one plays
                while True:
                    try:
                        gen, nxt = q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if gen == self._gen:
                        pending, pending_gen = asyncio.ensure_future(self.synth(nxt)), gen
                        break
                if this_gen != self._gen:
                    continue
                if pcm is not None and len(pcm):
                    self.player.play(pcm, 24000)
                    await asyncio.sleep(0.05)
                    while self.player.busy and this_gen == self._gen:
                        await asyncio.sleep(0.03)
        finally:
            if pending:
                pending.cancel()
            self.speaking = False

    async def wait(self):
        while self._task is not None and not self._task.done():
            await asyncio.sleep(0.03)
        while self.player.busy:
            await asyncio.sleep(0.03)

    async def speak(self, text: str):
        ch = SentenceChunker()
        for s in ch.feed(text) + ch.flush():
            self.say(s)
        await self.wait()

    def interrupt(self):
        self._gen += 1
        if self._q is not None:
            while not self._q.empty():
                try:
                    self._q.get_nowait()
                except asyncio.QueueEmpty:
                    break
        self.player.stop()

    @property
    def active(self) -> bool:
        return self.speaking or self.player.busy
