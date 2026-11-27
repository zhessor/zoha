"""
Settings for Zoha, loaded from .env (project folder) with sane defaults.

Everything is optional except an LLM key. Old v1 keys (GEMINI_API_KEY, WHISPER_MODEL,
EDGE_TTS_VOICE, MIC_GAIN_BOOST, AUDIO_DEVICE_INDEX ...) keep working.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
DATA_DIR = ROOT / "data"

load_dotenv(ENV_PATH, override=False)


def _s(key: str, default: str = "") -> str:
    v = os.getenv(key)
    return default if v is None else v.strip().strip('"').strip("'")


def _f(key: str, default: float) -> float:
    try:
        return float(_s(key, str(default)))
    except ValueError:
        return default


def _i(key: str, default: int) -> int:
    try:
        return int(float(_s(key, str(default))))
    except ValueError:
        return default


def _b(key: str, default: bool) -> bool:
    v = _s(key, "true" if default else "false").lower()
    return v in ("1", "true", "yes", "on", "y")


def _list(key: str, default: str) -> List[str]:
    return [x.strip().lower() for x in _s(key, default).split(",") if x.strip()]


@dataclass
class Settings:
    # Identity
    assistant_name: str = field(default_factory=lambda: _s("ASSISTANT_NAME", "Zoha"))
    user_name: str = field(default_factory=lambda: _s("USER_NAME", "there"))
    home_city: str = field(default_factory=lambda: _s("HOME_CITY", "Mumbai"))

    # Wake word
    wake_word: str = field(default_factory=lambda: _s("WAKE_WORD", "zoha").lower())
    wake_aliases: List[str] = field(default_factory=lambda: _list("WAKE_ALIASES", "jarvis"))
    follow_up_seconds: float = field(default_factory=lambda: _f("FOLLOW_UP_SECONDS", 8.0))
    barge_in: bool = field(default_factory=lambda: _b("BARGE_IN", True))
    use_parser: bool = field(default_factory=lambda: _b("USE_PARSER", True))  # False = every request goes to the AI

    # Microphone / VAD
    audio_device_index: Optional[int] = field(
        default_factory=lambda: None if _i("AUDIO_DEVICE_INDEX", -1) < 0 else _i("AUDIO_DEVICE_INDEX", -1)
    )
    mic_gain: float = field(default_factory=lambda: _f("MIC_GAIN_BOOST", 1.5))
    vad_threshold: float = field(default_factory=lambda: _f("VAD_THRESHOLD", 0.5))
    vad_end_silence_ms: int = field(default_factory=lambda: _i("VAD_END_SILENCE_MS", int(_f("VAD_PAUSE_THRESHOLD", 0.7) * 1000)))
    max_utterance_sec: float = field(default_factory=lambda: _f("VAD_PHRASE_TIME_LIMIT", 25.0))
    listen_timeout_sec: float = field(default_factory=lambda: _f("VAD_TIMEOUT", 6.0))

    # Speech to text
    whisper_model: str = field(default_factory=lambda: _s("WHISPER_MODEL", "auto"))
    whisper_device: str = field(default_factory=lambda: _s("WHISPER_DEVICE", "auto").lower())
    whisper_compute_type: str = field(default_factory=lambda: _s("WHISPER_COMPUTE_TYPE", "auto").lower())
    wake_model: str = field(default_factory=lambda: _s("WAKE_MODEL", "auto"))
    stt_language: str = field(default_factory=lambda: _s("STT_LANGUAGE", "en").lower())

    # Brain
    llm_provider: str = field(default_factory=lambda: _s("LLM_PROVIDER", "gemini").lower())
    gemini_api_key: str = field(default_factory=lambda: _s("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _s("GEMINI_MODEL", "gemini-2.5-flash"))
    llm_base_url: str = field(default_factory=lambda: _s("LLM_BASE_URL", "https://openrouter.ai/api/v1"))
    llm_api_key: str = field(default_factory=lambda: _s("LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _s("LLM_MODEL", "openrouter/auto"))
    llm_fallback: str = field(default_factory=lambda: _s("LLM_FALLBACK", "local").lower())
    local_llm_url: str = field(default_factory=lambda: _s("LOCAL_LLM_URL", "http://localhost:11434/v1"))
    local_llm_model: str = field(default_factory=lambda: _s("LOCAL_LLM_MODEL", "qwen3.5:4b"))
    # when the main local model can't see (e.g. the fine-tuned zoha-ft-4b), screen/page looks use this one
    local_vision_model: str = field(default_factory=lambda: _s("LOCAL_VISION_MODEL", "qwen3.5:4b"))
    local_llm_ctx: int = field(default_factory=lambda: _i("LOCAL_LLM_CTX", 8192))
    history_turns: int = field(default_factory=lambda: _i("CONVERSATION_HISTORY_LIMIT", 12))
    extra_instructions: str = field(default_factory=lambda: _s("EXTRA_INSTRUCTIONS"))

    # Voice
    tts_engine: str = field(default_factory=lambda: _s("TTS_ENGINE", "kokoro").lower())  # kokoro (local) | edge (online)
    kokoro_voice: str = field(default_factory=lambda: _s("KOKORO_VOICE", "af_heart"))
    kokoro_speed: float = field(default_factory=lambda: _f("KOKORO_SPEED", 1.05))
    tts_voice: str = field(default_factory=lambda: _s("EDGE_TTS_VOICE", "en-US-JennyNeural"))
    tts_rate: str = field(default_factory=lambda: _s("TTS_RATE", "+6%"))
    tts_pitch: str = field(default_factory=lambda: _s("TTS_PITCH", "+0Hz"))

    def llm_ready(self) -> bool:
        if self.llm_provider == "gemini":
            return (bool(self.gemini_api_key) and "your_" not in self.gemini_api_key) or self.llm_fallback == "local"
        if self.llm_provider == "local":
            return bool(self.local_llm_url)
        return bool(self.llm_base_url)

    def all_wake_words(self) -> List[str]:
        words = [self.wake_word] + [a for a in self.wake_aliases if a != self.wake_word]
        return [w for w in words if w]


# Mapping between dataclass fields and .env keys (used by the settings dialog)
ENV_KEYS = {
    "assistant_name": "ASSISTANT_NAME",
    "user_name": "USER_NAME",
    "home_city": "HOME_CITY",
    "wake_word": "WAKE_WORD",
    "wake_aliases": "WAKE_ALIASES",
    "follow_up_seconds": "FOLLOW_UP_SECONDS",
    "barge_in": "BARGE_IN",
    "use_parser": "USE_PARSER",
    "audio_device_index": "AUDIO_DEVICE_INDEX",
    "mic_gain": "MIC_GAIN_BOOST",
    "vad_threshold": "VAD_THRESHOLD",
    "vad_end_silence_ms": "VAD_END_SILENCE_MS",
    "max_utterance_sec": "VAD_PHRASE_TIME_LIMIT",
    "listen_timeout_sec": "VAD_TIMEOUT",
    "whisper_model": "WHISPER_MODEL",
    "whisper_device": "WHISPER_DEVICE",
    "whisper_compute_type": "WHISPER_COMPUTE_TYPE",
    "wake_model": "WAKE_MODEL",
    "stt_language": "STT_LANGUAGE",
    "llm_provider": "LLM_PROVIDER",
    "gemini_api_key": "GEMINI_API_KEY",
    "gemini_model": "GEMINI_MODEL",
    "llm_base_url": "LLM_BASE_URL",
    "llm_api_key": "LLM_API_KEY",
    "llm_model": "LLM_MODEL",
    "history_turns": "CONVERSATION_HISTORY_LIMIT",
    "llm_fallback": "LLM_FALLBACK",
    "local_llm_url": "LOCAL_LLM_URL",
    "local_llm_model": "LOCAL_LLM_MODEL",
    "local_vision_model": "LOCAL_VISION_MODEL",
    "extra_instructions": "EXTRA_INSTRUCTIONS",
    "tts_voice": "EDGE_TTS_VOICE",
    "tts_engine": "TTS_ENGINE",
    "kokoro_voice": "KOKORO_VOICE",
    "kokoro_speed": "KOKORO_SPEED",
    "local_llm_ctx": "LOCAL_LLM_CTX",
    "tts_rate": "TTS_RATE",
    "tts_pitch": "TTS_PITCH",
}


def save_env(updates: dict, path: Path = ENV_PATH) -> None:
    """Update/insert KEY=VALUE pairs in .env, keeping comments and other keys intact."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    out = []
    for line in lines:
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in remaining:
            key = m.group(1)
            out.append(f"{key}={_fmt(remaining.pop(key))}")
        else:
            out.append(line)
    if remaining:
        out.append("")
        for k, v in remaining.items():
            out.append(f"{k}={_fmt(v)}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    for k, v in updates.items():
        os.environ[k] = str(v) if not isinstance(v, list) else ",".join(v)


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ",".join(v)
    if v is None:
        return "-1"
    s = str(v)
    if any(c in s for c in " #\"'") and not (s.startswith('"') and s.endswith('"')):
        return '"' + s.replace('"', "'") + '"'
    return s


def load_settings() -> Settings:
    load_dotenv(ENV_PATH, override=True)
    return Settings()
