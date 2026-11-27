"""
Isolated GPU check for faster-whisper (run as a subprocess so a hang or a hard
crash in CUDA can never take Zoha down).

    python -m zoha.gpu_probe <model> <compute_type>

Prints one JSON line: {"ok": bool, "load": s, "first": s, "second": s, "error": str}
"""

from __future__ import annotations

import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("CUDA_CACHE_MAXSIZE", str(4 * 1024 ** 3))  # keep JIT-compiled kernels across runs


def main():
    model_name = sys.argv[1] if len(sys.argv) > 1 else "large-v3-turbo"
    compute = sys.argv[2] if len(sys.argv) > 2 else "float16"
    out = {"ok": False, "model": model_name, "compute": compute}
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from zoha.stt import _add_cuda_dll_dirs

        _add_cuda_dll_dirs()
        import numpy as np
        from faster_whisper import WhisperModel

        t = time.time()
        m = WhisperModel(model_name, device="cuda", compute_type=compute)
        out["load"] = round(time.time() - t, 2)
        audio = (np.random.default_rng(0).normal(0, 0.003, 32000)).astype(np.float32)
        for key in ("first", "second"):
            t = time.time()
            segs, _ = m.transcribe(audio, beam_size=1, language="en", max_new_tokens=4,
                                   without_timestamps=True, vad_filter=False, condition_on_previous_text=False,
                                   temperature=0.0)
            list(segs)
            out[key] = round(time.time() - t, 2)
        out["ok"] = out["second"] < 4.0
        if not out["ok"]:
            out["error"] = f"GPU too slow ({out['second']}s for 2 s of audio)"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:400]
    print("ZOHA_PROBE " + json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
