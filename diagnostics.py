#!/usr/bin/env python3
"""
Zoha diagnostics — checks every part separately and tells you what to fix.

    python diagnostics.py            # all checks
    python diagnostics.py --mic      # also record 4 s and show what Whisper heard
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

import numpy as np

OK, BAD, WARN = "  [ok]  ", "  [!!]  ", "  [--]  "


def section(t):
    print(f"\n{t}\n" + "-" * len(t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mic", action="store_true", help="record a 4 s test and transcribe it")
    ap.add_argument("--retest-gpu", action="store_true", help="run the GPU test again")
    a = ap.parse_args()

    from zoha.config import load_settings

    s = load_settings()

    section("1. Python & packages")
    print(f"{OK}Python {sys.version.split()[0]}")
    for mod in ("numpy", "sounddevice", "faster_whisper", "ctranslate2", "onnxruntime", "av", "edge_tts", "google.genai", "openai", "psutil", "PySide6", "dotenv", "playwright", "kokoro_onnx"):
        try:
            m = __import__(mod, fromlist=["x"])
            print(f"{OK}{mod} {getattr(m, '__version__', '')}")
        except Exception as e:
            print(f"{BAD}{mod} missing ({e}) → pip install -r requirements.txt")

    section("2. Audio devices")
    try:
        from zoha.audio import list_input_devices
        import sounddevice as sd

        for idx, name, d in list_input_devices():
            print(f"{OK}[{idx}] {name}{'  (default)' if d else ''}")
        print(f"{OK}output: {sd.query_devices(kind='output')['name']}")
    except Exception as e:
        print(f"{BAD}audio: {e}")

    section("3. Voice detection (Silero VAD)")
    try:
        from zoha.audio import make_vad, SileroVAD

        v = make_vad()
        print(f"{OK if isinstance(v, SileroVAD) else WARN}{type(v).__name__} loaded")
    except Exception as e:
        print(f"{BAD}{e}")

    section("4. GPU / speech recognition")
    from zoha.stt import Transcriber, _cudnn_present, cached_probe, run_gpu_probe

    try:
        import ctranslate2

        gpus = ctranslate2.get_cuda_device_count()
        print(f"{OK}CTranslate2 {ctranslate2.__version__}")
    except Exception:
        gpus = 0
    print(f"{OK if gpus else WARN}NVIDIA GPUs visible: {gpus}")
    print(f"{OK if _cudnn_present() else WARN}cuDNN 9 found: {_cudnn_present()}")
    if gpus and not _cudnn_present():
        print("        To use the GPU: pip install -r requirements-gpu.txt  (then rerun)")
    if gpus and _cudnn_present() and s.whisper_device != "cpu":
        gm = s.whisper_model if s.whisper_model != "auto" else "large-v3-turbo"
        gc = s.whisper_compute_type if s.whisper_compute_type != "auto" else "float16"
        res = cached_probe(gm, gc)
        if res is None or a.retest_gpu:
            print(f"        Testing {gm} ({gc}) on the GPU in a separate process…")
            print("        First run on an RTX 50-series card can take a few minutes while CUDA builds its kernels. Don't close this.")
            res = run_gpu_probe(gm, gc)
        if res.get("ok"):
            print(f"{OK}GPU works: load {res.get('load')}s, first run {res.get('first')}s, warm run {res.get('second')}s")
        else:
            print(f"{BAD}GPU test failed: {res.get('error')}")
            print("        Zoha will use the CPU. Try: pip install -U ctranslate2 faster-whisper, then: python diagnostics.py --retest-gpu")
    t = time.time()
    stt = Transcriber(s)
    print(f"{OK}main model {stt.model_name} on {stt.device}/{stt.compute}; wake pass {stt.wake_model_name}  ({time.time() - t:.1f}s)")

    if a.mic:
        import sounddevice as sd

        print("        Recording 4 seconds — say: “Zoha, what's the weather in Mumbai?”")
        rec = sd.rec(int(4 * 16000), samplerate=16000, channels=1, dtype="float32", device=s.audio_device_index)
        sd.wait()
        audio = rec[:, 0] * s.mic_gain
        rms = float(np.sqrt(np.mean(audio ** 2)))
        print(f"{OK if rms > 0.003 else WARN}input level RMS {rms:.4f}{'  (very quiet — raise mic boost in Settings)' if rms <= 0.003 else ''}")
        q, f = stt.quick(audio), stt.transcribe(audio)
        from zoha.wake import WakeMatcher

        wm = WakeMatcher(s.all_wake_words()).match(q.text)
        print(f"{OK}wake pass heard: {q.text!r}  → wake word {'DETECTED' if wm else 'not detected'}")
        print(f"{OK}accurate pass:   {f.text!r}  (confidence {f.confidence:.2f})")

    section("5. Brain")
    if not s.llm_ready():
        print(f"{BAD}no API key → add GEMINI_API_KEY to .env (free: https://aistudio.google.com/apikey)")
    else:
        from zoha.brain import Brain
        from zoha.memory import Memory
        from pathlib import Path
        import tempfile

        b = Brain(s, Memory(Path(tempfile.gettempdir()) / "zoha_diag_mem.json"))

        async def go():
            out, tools = "", []
            async for ev in b.run("Quick test: what's the time? Use your tool, then answer in under 10 words.", "voice"):
                if ev[0] == "text":
                    out += ev[1]
                elif ev[0] == "tool_start":
                    tools.append(ev[1])
            return out, tools

        try:
            t = time.time()
            out, tools = asyncio.run(go())
            print(f"{OK}{b.provider}:{b.model} replied in {time.time() - t:.1f}s: {out.strip()!r}")
            print(f"{OK if tools else WARN}tool calling: {'works (' + ', '.join(tools) + ')' if tools else 'model answered without tools'}")
        except Exception as e:
            print(f"{BAD}{e}")

    section("6. Zoha's browser (Playwright)")
    try:
        from zoha.tools import call_tool

        r = call_tool("browser_open", {"target": "https://example.com"})
        print(f"{OK if not r.startswith('Error') else BAD}{r.splitlines()[0][:150]}")
        if not r.startswith("Error"):
            time.sleep(2)
            print(f"{OK}{call_tool('browser_close', {})}")
    except Exception as e:
        print(f"{BAD}{e}")

    section("7. Voice")
    try:
        from zoha.tts import Speaker

        sp = Speaker(s)

        async def say():
            t = time.time()
            pcm = await sp.synth(f"Hi {s.user_name}, diagnostics complete.")
            print(f"{OK if pcm is not None else BAD}synthesis {'ok' if pcm is not None else 'failed'} in {time.time() - t:.2f}s ({s.tts_voice}, edge={'yes' if sp.edge_ok else 'offline fallback'})")
            if pcm is not None:
                sp.player.play(pcm, 24000)
                await asyncio.sleep(len(pcm) / 24000 + 0.3)

        asyncio.run(say())
        sp.player.close()
    except Exception as e:
        print(f"{BAD}{e}")
    print()


if __name__ == "__main__":
    main()
