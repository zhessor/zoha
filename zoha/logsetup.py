"""Logging to console + data/zoha.log (rotating)."""

import logging
import logging.handlers

from .config import DATA_DIR


def setup_logging(level=logging.INFO):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)
    fh = logging.handlers.RotatingFileHandler(DATA_DIR / "zoha.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    logging.getLogger("phonemizer").setLevel(logging.ERROR)  # harmless "words count mismatch" spam from Kokoro
    for noisy in ("httpx", "httpx2", "httpcore", "faster_whisper", "urllib3", "google_genai", "asyncio", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
