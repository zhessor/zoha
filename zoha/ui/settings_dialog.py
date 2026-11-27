"""The settings dialog (writes .env through zoha.config)."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget

from zoha.ui.theme import FAINT, MUTED, VOICES, WHISPER_MODELS


# ── Settings ─────────────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, settings, devices, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Zoha settings")
        self.setMinimumWidth(560)
        self.s = settings
        tabs = QTabWidget()

        def form():
            w = QWidget()
            f = QFormLayout(w)
            f.setLabelAlignment(Qt.AlignLeft)
            f.setFormAlignment(Qt.AlignTop)
            f.setVerticalSpacing(10)
            f.setContentsMargins(16, 16, 16, 16)
            return w, f

        # You
        w, f = form()
        self.user_name = QLineEdit(settings.user_name)
        self.home_city = QLineEdit(settings.home_city)
        self.extra = QTextEdit(settings.extra_instructions)
        self.extra.setPlaceholderText("Anything Zoha should always keep in mind (tone, your work, preferences)…")
        self.extra.setFixedHeight(90)
        f.addRow("Your name", self.user_name)
        f.addRow("Home city (weather)", self.home_city)
        f.addRow("Extra instructions", self.extra)
        tabs.addTab(w, "You")

        # Listening
        w, f = form()
        self.wake = QLineEdit(settings.wake_word)
        self.aliases = QLineEdit(", ".join(settings.wake_aliases))
        self.follow = QDoubleSpinBox()
        self.follow.setRange(0, 30)
        self.follow.setSuffix(" s")
        self.follow.setValue(settings.follow_up_seconds)
        self.barge = QCheckBox("Let me interrupt Zoha by saying her name or “stop”")
        self.barge.setChecked(settings.barge_in)
        self.mic = QComboBox()
        self.mic.addItem("System default", -1)
        for idx, name, _d in devices:
            self.mic.addItem(name, idx)
            if settings.audio_device_index == idx:
                self.mic.setCurrentIndex(self.mic.count() - 1)
        self.gain = QDoubleSpinBox()
        self.gain.setRange(0.5, 6.0)
        self.gain.setSingleStep(0.25)
        self.gain.setSuffix("×")
        self.gain.setValue(settings.mic_gain)
        self.vad = QDoubleSpinBox()
        self.vad.setRange(0.2, 0.9)
        self.vad.setSingleStep(0.05)
        self.vad.setValue(settings.vad_threshold)
        self.endsil = QSpinBox()
        self.endsil.setRange(300, 2500)
        self.endsil.setSingleStep(100)
        self.endsil.setSuffix(" ms")
        self.endsil.setValue(settings.vad_end_silence_ms)
        f.addRow("Wake word", self.wake)
        f.addRow("Also respond to", self.aliases)
        f.addRow("Follow-up window", self.follow)
        f.addRow("", self.barge)
        f.addRow("Microphone", self.mic)
        f.addRow("Mic boost", self.gain)
        f.addRow("Voice detection strictness", self.vad)
        f.addRow("Pause that ends a sentence", self.endsil)
        tabs.addTab(w, "Listening")

        # Speech recognition
        w, f = form()
        self.wmodel = QComboBox()
        self.wmodel.addItems(WHISPER_MODELS)
        self.wmodel.setEditable(True)
        self.wmodel.setCurrentText(settings.whisper_model)
        self.wdev = QComboBox()
        self.wdev.addItems(["auto", "cuda", "cpu"])
        self.wdev.setCurrentText(settings.whisper_device)
        self.lang = QComboBox()
        self.lang.addItems(["en", "auto", "hi", "mr"])
        self.lang.setEditable(True)
        self.lang.setCurrentText(settings.stt_language)
        hint = QLabel("Auto picks large-v3-turbo on your NVIDIA GPU and small.en on CPU. "
                      "Use auto language for Hindi/Marathi/Hinglish (multilingual model).")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{MUTED};")
        f.addRow("Model", self.wmodel)
        f.addRow("Run on", self.wdev)
        f.addRow("Language", self.lang)
        f.addRow("", hint)
        tabs.addTab(w, "Recognition")

        # Brain
        w, f = form()
        self.provider = QComboBox()
        self.provider.addItem("Google Gemini", "gemini")
        self.provider.addItem("Local only — Ollama on your GPU (unlimited, offline)", "local")
        self.provider.addItem("OpenAI-compatible (OpenRouter, LM Studio, Groq)", "openai")
        self.provider.setCurrentIndex(max(0, self.provider.findData(settings.llm_provider)))
        self.fallback = QCheckBox("When Gemini hits a limit or is offline, continue on the local model")
        self.fallback.setChecked(settings.llm_fallback == "local")
        self.lurl = QLineEdit(settings.local_llm_url)
        self.lmodel = QLineEdit(settings.local_llm_model)
        self.gkey = QLineEdit(settings.gemini_api_key)
        self.gkey.setEchoMode(QLineEdit.Password)
        self.gmodel = QLineEdit(settings.gemini_model)
        self.burl = QLineEdit(settings.llm_base_url)
        self.bkey = QLineEdit(settings.llm_api_key)
        self.bkey.setEchoMode(QLineEdit.Password)
        self.bmodel = QLineEdit(settings.llm_model)
        bhint = QLabel("Unlimited: install Ollama (winget install Ollama.Ollama) and run “ollama pull qwen3:8b”. "
                       "Gemini stays first for quality; the local model takes over whenever Gemini's free limit runs out.")
        bhint.setWordWrap(True)
        bhint.setStyleSheet(f"color:{MUTED};")
        f.addRow("Provider", self.provider)
        f.addRow("Gemini API key", self.gkey)
        f.addRow("Gemini model", self.gmodel)
        f.addRow("", self.fallback)
        f.addRow("Local server", self.lurl)
        f.addRow("Local model", self.lmodel)
        f.addRow("Other: base URL", self.burl)
        f.addRow("Other: API key", self.bkey)
        f.addRow("Other: model", self.bmodel)
        f.addRow("", bhint)
        tabs.addTab(w, "Brain")

        # Voice
        w, f = form()
        from zoha.local_tts import VOICES as KVOICES

        self.tts_engine = QComboBox()
        self.tts_engine.addItem("Local neural voice (Kokoro, offline, unlimited)", "kokoro")
        self.tts_engine.addItem("Microsoft Edge voices (online)", "edge")
        self.tts_engine.setCurrentIndex(max(0, self.tts_engine.findData(settings.tts_engine)))
        self.kvoice = QComboBox()
        for vid, name in KVOICES:
            self.kvoice.addItem(name, vid)
        self.kvoice.setCurrentIndex(max(0, self.kvoice.findData(settings.kokoro_voice)))
        self.kspeed = QDoubleSpinBox()
        self.kspeed.setRange(0.7, 1.5)
        self.kspeed.setSingleStep(0.05)
        self.kspeed.setSuffix("×")
        self.kspeed.setValue(settings.kokoro_speed)
        f.addRow("Voice engine", self.tts_engine)
        f.addRow("Local voice", self.kvoice)
        f.addRow("Local voice speed", self.kspeed)
        self.voice = QComboBox()
        for vid, name in VOICES:
            self.voice.addItem(name, vid)
        if settings.tts_voice not in [v for v, _ in VOICES]:
            self.voice.addItem(settings.tts_voice, settings.tts_voice)
        self.voice.setCurrentIndex(max(0, self.voice.findData(settings.tts_voice)))
        self.rate = QSpinBox()
        self.rate.setRange(-30, 40)
        self.rate.setSuffix(" %")
        self.rate.setValue(int(re.sub(r"[^\d-]", "", settings.tts_rate) or 0))
        self.preview = QPushButton("Play a sample")
        f.addRow("Online voice", self.voice)
        f.addRow("Online voice speed", self.rate)
        f.addRow("", self.preview)
        tabs.addTab(w, "Voice")

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        note = QLabel("Voice and speed changes apply right away. Other changes restart Zoha.")
        note.setStyleSheet(f"color:{FAINT};")
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        row = QHBoxLayout()
        row.addWidget(note, 1)
        row.addWidget(btns)
        lay.addLayout(row)

    def values(self) -> dict:
        return {
            "user_name": self.user_name.text().strip() or "there",
            "home_city": self.home_city.text().strip() or "Mumbai",
            "extra_instructions": self.extra.toPlainText().strip().replace("\n", " "),
            "wake_word": self.wake.text().strip().lower() or "zoha",
            "wake_aliases": [a.strip().lower() for a in self.aliases.text().split(",") if a.strip()],
            "follow_up_seconds": self.follow.value(),
            "barge_in": self.barge.isChecked(),
            "audio_device_index": self.mic.currentData(),
            "mic_gain": self.gain.value(),
            "vad_threshold": round(self.vad.value(), 2),
            "vad_end_silence_ms": self.endsil.value(),
            "whisper_model": self.wmodel.currentText().strip(),
            "whisper_device": self.wdev.currentText(),
            "stt_language": self.lang.currentText().strip(),
            "llm_provider": self.provider.currentData(),
            "gemini_api_key": self.gkey.text().strip(),
            "gemini_model": self.gmodel.text().strip(),
            "llm_base_url": self.burl.text().strip(),
            "llm_api_key": self.bkey.text().strip(),
            "llm_model": self.bmodel.text().strip(),
            "llm_fallback": "local" if self.fallback.isChecked() else "none",
            "local_llm_url": self.lurl.text().strip() or "http://localhost:11434/v1",
            "local_llm_model": self.lmodel.text().strip() or "qwen3:8b",
            "tts_voice": self.voice.currentData(),
            "tts_rate": f"{self.rate.value():+d}%",
            "tts_engine": self.tts_engine.currentData(),
            "kokoro_voice": self.kvoice.currentData(),
            "kokoro_speed": round(self.kspeed.value(), 2),
        }
