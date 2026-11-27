"""
ZohaEngine — the orchestrator. UI-agnostic: the GUI and the headless CLI both drive it.

Flow
  mic ─► AudioHub (Silero VAD) ─► utterance
        ├─ standby : fast wake-word pass (tiny) → if "Zoha" → accurate pass (main model)
        ├─ awake   : (after wake / push-to-talk / follow-up window) accurate pass directly
        └─ busy    : barge-in check – "Zoha…" or "stop" interrupts Zoha mid-sentence
  text ─► control intents (stop/clear/sleep/exit) ─► instant intents (volume, pause…)
       ─► Brain (LLM + tools, streamed) ─► SentenceChunker ─► Speaker (Edge TTS)

Events are delivered through `emit(event, **data)` from the engine thread.
"""

from __future__ import annotations

import asyncio
import os
import re
import difflib
import itertools
import logging
import threading
import time
from typing import Callable, Dict, List, Optional

from . import intents
from . import learn
from . import tools as T
from .audio import CHIME_ALARM, CHIME_DONE, CHIME_ERROR, CHIME_WAKE, AudioHub, Player, Utterance
from .brain import Brain
from .config import Settings
from .memory import Memory
from .tts import SentenceChunker, Speaker
from .wake import WakeMatcher

log = logging.getLogger("zoha.engine")

VOCAB = "Zoha, open Spotify. Play lofi on YouTube. Open VS Code, Chrome, WhatsApp, Windsurf. Set a timer. What's the weather in Mumbai?"


def _only_wake_words(text: str, words) -> bool:
    """'Zoha Jarvis' / 'Jarvis Zoha' = Whisper echoing its hotword list, not a person talking."""
    import re as _re

    toks = [t for t in _re.sub(r"[^a-z ]", " ", text.lower()).split() if t not in ("hey", "hi", "ok", "okay")]
    ws = {w for w in words}
    return len(toks) >= 2 and all(t in ws for t in toks) and len(set(toks)) >= 2


FAST_LOCAL = {"open_app", "close_app", "play_youtube", "play_spotify", "web_search", "create_note", "set_timer",
              "get_weather", "system_status", "media_control", "set_volume", "browser_open", "browser_close",
              "browser_video", "browser_window"}


class ZohaEngine:
    def __init__(self, settings: Settings, emit: Callable[..., None]):
        self.s = settings
        self._emit = emit
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self.ready = threading.Event()
        self.state = "BOOTING"
        self.muted = False
        self.awake_until = 0.0
        self.turn_task: Optional[asyncio.Task] = None
        self.timers: Dict[int, dict] = {}
        self._tid = itertools.count(1)
        self.matcher = WakeMatcher(settings.all_wake_words())
        self.memory = Memory(max_turns=settings.history_turns)
        self.player = Player(24000)
        self.stt = None
        self.hub: Optional[AudioHub] = None
        self.brain = Brain(settings, self.memory)
        self.speaker = Speaker(settings, self.player)
        self._utt_q: Optional[asyncio.Queue] = None
        self._stopping = False
        self.local_status = "not needed"
        self.local_ready = False
        self.voice_status = ""
        self.learner = learn.get()
        self._heard = ("", None)
        # rolling summary: off by default – the 4B model's summaries invented facts (ROLLING_SUMMARY=1 to try again)
        if os.getenv("ROLLING_SUMMARY", "0") == "1":
            self.memory.on_dropped = self._summarize_bg
        else:
            self.memory.summary = {}

    def _summarize_bg(self, turns):
        """Old turns fell out of the history window → fold them into the running summary (background thread)."""
        def work():
            try:
                text = learn.summarize(self.s.local_llm_url, self.brain.local_runtime_model, self.memory.summary_text(), turns)
                if text:
                    self.memory.set_summary(text)
                    log.info("Conversation summary updated (%d words)", len(text.split()))
            except Exception:
                log.exception("summary failed")
        threading.Thread(target=work, daemon=True, name="zoha-summary").start()

    # ── public, thread-safe API ─────────────────────────────────────────
    def start(self):
        self._thread = threading.Thread(target=self._thread_main, name="zoha-engine", daemon=True)
        self._thread.start()

    def _call(self, fn, *a):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(fn, *a)

    def push_to_talk(self):
        self._call(self._ptt)

    def send_text(self, text: str):
        self._call(self._start_turn, text, "text")

    def interrupt(self):
        self._call(self._interrupt, True)

    def set_muted(self, muted: bool):
        self._call(self._set_muted, muted)

    def set_device(self, index: Optional[int]):
        self._call(self._set_device, index)

    def clear_memory(self):
        self._call(self._clear)

    def set_voice(self, voice: str):
        self.speaker.voice = voice
        self.s.tts_voice = voice

    def shutdown(self):
        self._stopping = True
        self._call(self._shutdown)

    # ── internals ─────────────────────────────────────────────────────
    def emit(self, event: str, **data):
        if event in ("tool_start", "tool_end", "reply_end", "brain"):
            try:
                self.learner.on_event(event, data)
            except Exception:
                log.exception("journal failed")
        try:
            self._emit(event, **data)
        except Exception:
            log.exception("emit failed")

    def _set_state(self, st: str):
        if st != self.state:
            self.state = st
            self.emit("state", state=st)

    def _thread_main(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        except Exception as e:
            log.exception("Engine crashed")
            self.emit("error", text=f"Engine crashed: {e}")
        finally:
            try:
                self.loop.close()
            except Exception:
                pass

    async def _main(self):
        self._utt_q = asyncio.Queue()
        self._set_state("BOOTING")
        T.CTX.memory = self.memory
        T.CTX.settings = self.s
        try:
            from . import site_plugin as zhessor_site

            zhessor_site.warm()  # loads the website's editable fields in the background (no-op without a key)
        except Exception:
            log.exception("website control unavailable")
        T.CTX.schedule = self._schedule_threadsafe
        T.CTX.list_timers = self._list_timers
        T.CTX.cancel_timer = self._cancel_timer_threadsafe
        T.CTX.vision = self.brain.vision_fn() if self.s.llm_provider == "gemini" else None
        T.CTX.writer = self.brain.text_fn() if self.s.llm_provider == "gemini" else None
        self.player.on_level = lambda lv: self.emit("out_level", level=lv)

        asyncio.ensure_future(self._prepare_local())
        import importlib.util as _iu

        if _iu.find_spec("playwright") is None:
            log.warning("Browser: Playwright not installed")
            self.emit("error", text="My own browser is off because Playwright isn't installed. Run: pip install playwright")
        else:
            log.info("Browser: Playwright available")
        self.emit("info", text="Loading speech recognition…")
        try:
            from .stt import Transcriber

            self.stt = await asyncio.to_thread(
                Transcriber, self.s,
                lambda m: self.emit("info", text=m),
                lambda: self.emit("ready", **self._info()),
            )
        except Exception as e:
            log.exception("STT failed to load")
            self.emit("error", text=f"Speech recognition failed to load: {e}. Typing still works.")

        if self.stt is not None:
            try:
                self.hub = AudioHub(
                    self.s,
                    on_level=lambda lv: self.emit("mic_level", level=lv),
                    on_speech_start=lambda: self._call(self._on_speech_start),
                    on_utterance=lambda u: self._call(self._utt_q.put_nowait, u),
                )
                self.hub.start()
            except Exception as e:
                log.exception("Mic failed")
                self.emit("error", text=f"Microphone error: {e}. Pick another mic or type instead.")

        self.emit("ready", **self._info())
        if not self.s.llm_ready():
            self.emit("error", text="No LLM key set — add GEMINI_API_KEY (free at aistudio.google.com) in Settings. Basic commands still work.")
        self.ready.set()
        self._set_state("STANDBY" if self.hub and self.hub.is_open else "MUTED")
        self._watch = asyncio.ensure_future(self._watch_awake())
        self._aware_task = asyncio.ensure_future(self._awareness_loop())
        await self._consume()

    async def _prepare_local(self):
        """Background: get the local voice and the local brain ready (downloads on first run)."""
        if self.s.tts_engine == "kokoro":
            self.voice_status = await asyncio.to_thread(self.speaker.prepare, lambda m: self.emit("info", text=m))
            if not self.speaker.kokoro.ready:
                self.emit("error", text=f"{self.voice_status}. Using the Windows voice meanwhile.")
            self.emit("ready", **self._info())
        if self.s.llm_provider == "local" or self.s.llm_fallback == "local":
            from . import local_llm

            better = local_llm.recommended(self.s.local_llm_model)
            if better != self.s.local_llm_model:
                from .config import save_env

                log.info("Switching local model %s → %s (thinking-only models are too slow for voice)", self.s.local_llm_model, better)
                self.emit("info", text=f"Switching the local brain to {better}: same size, but it answers directly "
                                       f"instead of reasoning out loud first.")
                self.s.local_llm_model = better
                save_env({"LOCAL_LLM_MODEL": better})
            quiet = self.s.llm_provider != "local"  # as a fallback, don't download unasked
            if quiet and not local_llm.server_up(self.s.local_llm_url) and not local_llm.find_ollama():
                self.local_status = "Ollama not installed"
                return
            ok, res = await asyncio.to_thread(local_llm.ensure_ready, self.s.local_llm_url, self.s.local_llm_model,
                                              self.s.local_llm_ctx, lambda m: self.emit("info", text=m))
            if ok:
                self.brain.local_runtime_model = res
                self.brain._local_ok, self.brain._local_checked = True, time.time()
                self.local_ready = True
                self.local_status = "ready"
                await asyncio.to_thread(local_llm.warm_up, self.s.local_llm_url, res)
                caps = await asyncio.to_thread(local_llm.model_caps, self.s.local_llm_url, res)
                self.brain.local_thinks = "thinking" in caps
                if self.s.llm_provider == "local":
                    T.CTX.vision = self.brain.vision_fn(caps)
                    T.CTX.writer = self.brain.text_fn()
                    log.info("Local brain capabilities: %s (vision for the browser: %s)", caps, bool(T.CTX.vision))
                share = await asyncio.to_thread(local_llm.gpu_share, self.s.local_llm_url, res)
                log.info("Local brain %s: %s on GPU", res, f"{share:.0%}" if share is not None else "unknown share")
                if share is not None and share < 0.9:
                    self.emit("error", text=(f"Only {share:.0%} of the local brain fits on your GPU, so answers will be slow. "
                                             "Close other GPU-heavy apps (games, other Zoha windows) or pick a smaller model "
                                             "in Settings → Brain (e.g. qwen3:1.7b)."))
                elif self.s.llm_provider == "local":
                    self.emit("info", text=f"Local brain ready: {self.s.local_llm_model}, fully on your GPU. No limits, no internet needed.")
            else:
                self.local_status = res
                if self.s.llm_provider == "local":
                    self.emit("error", text=res)
            self.emit("ready", **self._info())

    # ── live awareness ──────────────────────────────────────────────
    _media_line = ""
    _media_at = 0.0

    def _snapshot_media(self) -> str:
        info = T._media_session("status") if T.WIN else None
        if not info or info.get("none"):
            return "Media: nothing playing." if info else ""
        what = info.get("title") or "something"
        if info.get("artist"):
            what += f" by {info['artist']}"
        return f"Media: {what} in {T._app_name(info.get('app', ''))} – {(info.get('after') or info.get('before') or '?').lower()}."

    def _snapshot_fast(self) -> List[str]:
        lines = []
        try:
            from .browser import _BROWSER

            if _BROWSER is not None and _BROWSER.is_open():
                info = _BROWSER.call(lambda: (_BROWSER.page.title(), _BROWSER.page.url,
                                              _BROWSER.page.evaluate("() => { const v=document.querySelector('video'); return v ? "
                                                                     "(v.paused?'paused':'playing') + (document.fullscreenElement?', full screen':'') : '' }"))
                                     if _BROWSER._alive() else None, timeout=4)
                if info:
                    lines.append(f"Your browser (browser_* tools) is open on: {info[0]} – {info[1]}" + (f" (video {info[2]})" if info[2] else ""))
        except Exception:
            pass
        wins = [f"{t[:60]}" for t, p in T.visible_windows()[:8] if "zoha" not in t.lower()]
        if wins:
            lines.append("Open windows (front first): " + "; ".join(wins))
        if self.timers:
            lines.append("Timers: " + self._list_timers().replace("\n", "; "))
        return lines

    async def _refresh_awareness(self, media: bool = True):
        try:
            if media and T.WIN:
                self._media_line = await asyncio.to_thread(self._snapshot_media)
                self._media_at = time.time()
            fast = await asyncio.to_thread(self._snapshot_fast)
            self.brain.awareness = "\n".join(([self._media_line] if self._media_line else []) + fast)
        except Exception as e:
            log.debug("awareness refresh failed: %s", e)

    async def _awareness_loop(self):
        while not self._stopping:
            await self._refresh_awareness(media=True)
            await asyncio.sleep(20)

    def _info(self) -> dict:
        st = self.stt
        return {
            "stt": f"{st.model_name} on {'GPU' if st.device == 'cuda' else 'CPU'}" if st else "speech offline",
            "wake": st.wake_model_name if st else "-",
            "gpu": getattr(st, "gpu_status", "") if st else "",
            "brain": self.brain.label() if self.s.llm_ready() else "no API key",
            "voice": (f"{self.s.kokoro_voice} (local)" if self.s.tts_engine == "kokoro" and self.speaker.kokoro.ready
                      else self.s.tts_voice if self.s.tts_engine != "kokoro" else "Windows voice"),
            "wake_words": self.s.all_wake_words(),
        }

    async def _watch_awake(self):
        while not self._stopping:
            await asyncio.sleep(0.25)
            busy = self.turn_task is not None and not self.turn_task.done()
            if busy or self.muted:
                continue
            if self.state == "LISTENING" and time.time() > self.awake_until:
                self._set_state("STANDBY")

    def _on_speech_start(self):
        if self.state in ("LISTENING",) or time.time() < self.awake_until:
            self.emit("hearing", active=True)

    def _awake(self, seconds: float):
        self.awake_until = time.time() + seconds
        if not (self.turn_task and not self.turn_task.done()):
            self._set_state("LISTENING")

    def _ptt(self):
        if self.speaker.active or (self.turn_task and not self.turn_task.done()):
            self._interrupt(False)
        if self.hub is None:
            self.emit("error", text="Microphone isn't available — type your request instead.")
            return
        if self.muted:
            self._set_muted(False)
        self.hub.flush()
        self.player.play(CHIME_WAKE, 24000)
        self._awake(max(self.s.listen_timeout_sec, 6.0))

    def _interrupt(self, say_chime: bool):
        self.speaker.interrupt()
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
        if say_chime:
            self.player.play(CHIME_DONE, 24000)
        self.emit("interrupted")
        self._set_state("STANDBY")

    def _set_muted(self, muted: bool):
        self.muted = muted
        if self.hub:
            if muted:
                self.hub.stop()
            else:
                try:
                    self.hub.start()
                except Exception as e:
                    self.emit("error", text=f"Microphone error: {e}")
                    return
        self._set_state("MUTED" if muted else "STANDBY")

    def _set_device(self, idx):
        if self.hub:
            try:
                self.hub.set_device(idx)
                self.emit("info", text="Microphone switched.")
            except Exception as e:
                self.emit("error", text=f"Couldn't open that microphone: {e}")

    def _clear(self):
        self.memory.clear_conversation()
        self.emit("info", text="Conversation context cleared (long-term memory kept).")

    def _shutdown(self):
        self._interrupt(False)
        try:
            from .browser import shutdown as browser_shutdown

            browser_shutdown()
        except Exception:
            pass
        for t in list(self.timers.values()):
            t["handle"].cancel()
        if self.hub:
            self.hub.shutdown()
        self.player.close()
        if getattr(self, "_watch", None):
            self._watch.cancel()
        if getattr(self, "_aware_task", None):
            self._aware_task.cancel()
        if self._utt_q:
            self._utt_q.put_nowait(None)

    # ── utterance handling ──────────────────────────────────────────────
    async def _consume(self):
        while True:
            utt = await self._utt_q.get()
            if utt is None:
                return
            try:
                await self._on_utterance(utt)
            except Exception as e:
                log.exception("utterance handling failed")
                self.emit("error", text=str(e))

    def _busy(self) -> bool:
        return (self.turn_task is not None and not self.turn_task.done()) or self.speaker.active

    async def _on_utterance(self, utt: Utterance):
        if self.stt is None or self.muted:
            return
        now = time.time()

        if self._busy():
            if not self.s.barge_in:
                return
            q = await asyncio.to_thread(self.stt.quick, utt.audio, False)
            if _only_wake_words(q.text, self.s.all_wake_words()):
                return
            wm = self.matcher.match(q.text)
            ctl = intents.control(q.text)
            if wm or ctl == "stop":
                log.info("Barge-in: %r", q.text)
                self._interrupt(False)
                if wm and wm.command:
                    full = await self._accurate(utt, wm)
                    if full:
                        self._start_turn(full, "voice")
                        return
                self.player.play(CHIME_WAKE, 24000)
                self._awake(self.s.listen_timeout_sec)
            return

        awake = now < self.awake_until + 0.4 or utt.started < self.awake_until
        if awake:
            self._set_state("THINKING")
            t0 = time.time()
            tr = await asyncio.to_thread(self.stt.transcribe, utt.audio, self.learner.stt_vocab(VOCAB))
            text = tr.text
            log.info("Heard (awake, conf %.2f, %.2fs): %r", tr.confidence, time.time() - t0, text)
            self._heard = (text, tr.confidence)
            if text and tr.confidence < 0.45 and len(text.split()) <= 4 and not intents.control(text):
                # a mumbled fragment (e.g. the tail of something said to someone else) – don't act on it
                log.info("Ignoring low-confidence fragment %r", text)
                self.emit("hearing", active=False)
                self._awake(max(3.0, self.awake_until - time.time()))
                if self.state == "THINKING":
                    self._set_state("LISTENING")
                return
            if not text:
                self.emit("hearing", active=False)
                self._awake(max(2.0, self.awake_until - time.time()))
                if self.state == "THINKING":
                    self._set_state("LISTENING")
                return
            wm = self.matcher.match(text)
            if wm:
                if not wm.command:
                    self.player.play(CHIME_WAKE, 24000)
                    self._awake(self.s.listen_timeout_sec)
                    return
                text = wm.command
            self._start_turn(text, "voice")
            return

        # standby → wake-word pass
        q = await asyncio.to_thread(self.stt.quick, utt.audio)
        if not q.text or _only_wake_words(q.text, self.s.all_wake_words()):
            return
        wm = self.matcher.match(q.text)
        log.debug("standby heard: %r -> %s", q.text, wm)
        if not wm:
            self.emit("overheard", text=q.text)
            return
        if not wm.command:
            log.info("Wake word only (%r)", q.text)
            self.hub.flush()
            self.player.play(CHIME_WAKE, 24000)
            self.emit("woke")
            self._awake(self.s.listen_timeout_sec)
            return
        self._set_state("THINKING")
        self.emit("woke")
        full = await self._accurate(utt, wm, q.text)
        if full:
            self._start_turn(full, "voice")
        else:
            self.player.play(CHIME_WAKE, 24000)
            self._awake(self.s.listen_timeout_sec)

    async def _accurate(self, utt: Utterance, wm, quick_text: str = "") -> str:
        """Re-transcribe a wake+command utterance with the main model and strip the wake word."""
        if self.stt.shared and quick_text:
            return wm.command
        tr = await asyncio.to_thread(self.stt.transcribe, utt.audio, self.learner.stt_vocab(VOCAB))
        log.info("Heard (wake+command, conf %.2f): %r", tr.confidence, tr.text)
        self._heard = (tr.text, tr.confidence)
        if not tr.text:
            return wm.command
        wm2 = self.matcher.match(tr.text)
        if wm2:
            return wm2.command
        # main model spelled the wake word differently: drop a leading token that looks like it
        toks = tr.text.split()
        lead = [t.strip(",.!?").lower() for t in toks[:3]]
        for i, t in enumerate(lead):
            if t in ("hey", "hi", "ok", "okay"):
                continue
            sim = max(difflib.SequenceMatcher(None, t, self.s.wake_word).ratio(),
                      difflib.SequenceMatcher(None, t, "hey" + self.s.wake_word).ratio())
            if wm.position != "end" and sim >= 0.5:
                return " ".join(toks[i + 1 :]).lstrip(",. ") or wm.command
            break
        if wm.position == "end" and toks:
            last = toks[-1].strip(",.!?").lower()
            if difflib.SequenceMatcher(None, last, self.s.wake_word).ratio() >= 0.5:
                return " ".join(toks[:-1]).rstrip(",. ")
        return tr.text

    # ── a conversational turn ─────────────────────────────────────────
    def _start_turn(self, text: str, modality: str):
        text = (text or "").strip()
        if not text:
            return
        if modality != "voice":
            self._heard = (text, None)
        text = self.learner.apply_aliases(text)
        if self.turn_task and not self.turn_task.done():
            self._interrupt(False)
        self.turn_task = asyncio.ensure_future(self._turn(text, modality))

    async def _turn(self, text: str, modality: str):
        """Wraps a turn with the journal, and handles corrections ("no, I meant Air LLM")."""
        L = self.learner
        heard, conf = self._heard if self._heard[0] else (text, None)
        self._heard = ("", None)
        self.brain.turn_flags = []
        L.begin(text, modality, heard, conf)
        if not self.s.use_parser and L.cur is not None:
            L.cur["mode"] = "ai_only"
        interrupted, note = False, ""
        try:
            corr = None
            try:
                corr = L.correction(text)
            except Exception:
                log.exception("correction check failed")
            if corr:
                right, wrong, redo = corr
                if L.prev:
                    L.feedback(L.prev["id"], bad=True, why=f"corrected {wrong!r} → {right!r}")
                note = f"correction:{wrong}->{right}"
                if redo:
                    log.info("Correction %r → %r: redoing %r", wrong, right, redo)
                    self.speaker.say(f"Got it, {right}.")
                    L.cur["text"] = redo
                    text = redo
                else:
                    return await self._say_simple(f"Got it. I'll hear that as {right} from now on.", text)
            await self._turn_inner(text, modality)
        except asyncio.CancelledError:
            interrupted = True
            raise
        finally:
            L.end(flags=list(getattr(self.brain, "turn_flags", []) or []), interrupted=interrupted, note=note)

    async def _turn_inner(self, text: str, modality: str):
        T.CTX.last_user_text = text
        T.CTX.turn_started = time.time()
        self.emit("user", text=text, modality=modality)
        self.emit("hearing", active=False)
        self._set_state("THINKING")
        voice = modality == "voice"
        self._voice_turn = voice
        spoken_any = False
        reply = ""
        try:
            ctl = intents.control(text)
            if ctl == "stop":
                self.player.play(CHIME_DONE, 24000)
                self.awake_until = 0
                self._set_state("STANDBY")
                return
            if ctl == "clear":
                self.memory.clear_conversation()
                return await self._say_simple("Fresh start. Context cleared.", text, store=False)
            if ctl in ("wakeonly", "followup"):
                from .config import save_env

                self.s.follow_up_seconds = 0.0 if ctl == "wakeonly" else 8.0
                save_env({"FOLLOW_UP_SECONDS": self.s.follow_up_seconds})
                self.awake_until = 0
                msg = (f"Got it. I'll only respond when you say {self.s.wake_word.title()}." if ctl == "wakeonly"
                       else "Okay, I'll keep listening for a few seconds after I answer.")
                await self._say_simple(msg, text, store=False, follow=False)
                return
            if ctl == "sleep":
                self.awake_until = 0
                await self._say_simple("Okay. Say my name when you need me.", text, store=False, follow=False)
                return
            if ctl == "exit":
                await self._say_simple(f"Goodbye, {self.s.user_name}.", text, store=False, follow=False)
                self.emit("exit")
                return

            # 0a) answering "<website change>. Should I go ahead?" – only a clear yes applies it (the AI never can);
            #     no cancels it; anything else cancels it too, so a later "yes" can't apply an old proposal
            from . import site_plugin as SITE

            if SITE.pending_site():
                if SITE.is_confirm(text):
                    kind = (SITE.pending_site() or {}).get("kind")
                    res = await asyncio.to_thread(SITE.apply_pending)
                    self.emit("tool_start", name="site_apply", label="Sending the email" if kind == "reply" else "Changing the website",
                              icon="🌐", args={})
                    self.emit("tool_end", name="site_apply", result=res, ok=not res.startswith("Error"))
                    if res.startswith("EXPIRED: "):  # re-drafted after expiry → read it again and wait for a NEW yes
                        q = re.search(r"Ask the user exactly: '(.+)' Do nothing else\.", res, re.S)
                        return await self._say_simple("That one had expired, so I prepared it again. " + (q.group(1) if q else ""), text)
                    return await self._say_simple(res.replace("Error: ", ""), text)
                if SITE.NO_RX.match(text) and len(text.split()) <= 3:
                    return await self._say_simple(await asyncio.to_thread(SITE.cancel_pending), text)
                await asyncio.to_thread(SITE.cancel_pending, False)
                log.info("Website change cancelled: the user moved on without saying yes")
            # 0a2) generic ask-first gate (publishing a site, ...): only a clear yes runs it; anything else cancels it
            from . import confirm as CONFIRM

            if CONFIRM.pending():
                if CONFIRM.is_yes(text):
                    self.emit("tool_start", name="confirmed_action", label="Doing it", icon="✅", args={})
                    res = await asyncio.to_thread(CONFIRM.apply)
                    self.emit("tool_end", name="confirmed_action", result=res, ok=not res.startswith("Error"))
                    return await self._say_simple(_spoken(res.replace("Error: ", "")), text)
                if CONFIRM.is_no(text):
                    CONFIRM.cancel()
                    return await self._say_simple("Okay, I won't.", text)
                CONFIRM.cancel()
            # 0b) answering "should I shut down the PC?" – yes executes, anything else cancels the question
            pending = T.pending_power()
            if pending:
                if T.YES_RX.match(text):
                    return await self._say_simple(_spoken(await self._run_tool("power", {"action": pending, "confirmed": True})), text)
                T._POWER_PENDING.clear()
            # 1) plain commands → understood and executed instantly, no LLM
            handled = await self._run_commands(text)
            if handled:
                return
            local_pending = self.s.llm_provider == "local" and not self.local_ready
            if not self.s.llm_ready() or local_pending:
                route = intents.offline_route(text)
                if route:
                    result = await self._run_tool(*route)
                    return await self._say_simple(result, text)
                if local_pending:
                    msg = ("My local brain is still getting ready. " if self.local_status in ("not needed", "") or "Download" in self.local_status
                           else self.local_status)
                    return await self._say_simple(msg if msg.strip() else "My local brain is still getting ready.", text, store=False)
                return await self._say_simple("I need an LLM key for that. Open Settings and add your Gemini API key.", text, store=False)

            await self._refresh_awareness(media=time.time() - self._media_at > 8)
            chunker = SentenceChunker()
            self.emit("reply_start")
            full = ""
            t_brain = time.time()
            first_text = None
            try:
                async for ev in self.brain.run(text, modality):
                    kind = ev[0]
                    if kind == "text":
                        if first_text is None:
                            first_text = time.time() - t_brain
                            log.info("Brain first words after %.2fs", first_text)
                        self.emit("reply_delta", text=ev[1])
                        for sent in chunker.feed(ev[1]):
                            self.speaker.say(sent)
                            spoken_any = True
                            self._set_state("SPEAKING")
                    elif kind == "tool_start":
                        t = T.REGISTRY.get(ev[1])
                        self.emit("tool_start", name=ev[1], label=t.label if t else ev[1], icon=t.icon if t else "⚡", args=ev[2])
                    elif kind == "tool_end":
                        self.emit("tool_end", name=ev[1], result=ev[2], ok=not str(ev[2]).startswith("Error"))
                    elif kind == "notice":
                        self.emit("info", text=ev[1])
                        self.emit("brain", name=self.brain.last_used)
                    elif kind == "done":
                        full = ev[1]
                        self.emit("brain", name=self.brain.last_used)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("Brain failed")
                route = None if spoken_any else intents.offline_route(text)
                if route:
                    result = await self._run_tool(*route)
                    self.emit("reply_end", text="")
                    return await self._say_simple(result, text)
                msg = _friendly_error(e)
                self.emit("reply_delta", text=("\n\n" if full else "") + msg)
                self.speaker.say(msg)
                spoken_any = True
                full = (full + " " + msg).strip()
            for sent in chunker.flush():
                self.speaker.say(sent)
                spoken_any = True
            self.emit("reply_end", text=full)
            reply = full
            if spoken_any:
                self._set_state("SPEAKING")
            await self.speaker.wait()
            if reply:
                self.memory.add_turn(text, reply)
            self._after_speaking(voice)
        except asyncio.CancelledError:
            self.emit("reply_end", text=reply)
            raise

    def _nlu_ctx(self):
        from .nlu import Ctx

        try:
            from .browser import _BROWSER

            if _BROWSER is not None and _BROWSER.is_open():
                return Ctx(browser_open=True, browser_url=_BROWSER.current_url())
        except Exception:
            pass
        return Ctx()

    async def _run_commands(self, text: str) -> bool:
        """Execute what the command parser understood. Returns True if the turn is fully handled."""
        from . import nlu

        if not self.s.use_parser and self.s.llm_ready() and not (self.s.llm_provider == "local" and not self.local_ready):
            return False  # AI-only mode (USE_PARSER=false): the brain handles everything
        acts = nlu.parse(text, await asyncio.to_thread(self._nlu_ctx))
        if not acts:
            return False
        t0 = time.time()
        spoken = []
        for i, act in enumerate(acts):
            t = T.REGISTRY.get(act.tool)
            res = await asyncio.to_thread(T.call_tool, act.tool, act.args)
            failed = res.startswith("Error")
            if failed and act.soft and len(acts) == 1 and self.s.llm_ready() and not (
                    self.s.llm_provider == "local" and not self.local_ready):
                log.info("Command guess %s%s failed (%s) – handing to the brain", act.tool, act.args, res[:80])
                return False  # e.g. "open <something that isn't an app>" → let the LLM think
            self.emit("tool_start", name=act.tool, label=t.label if t else act.tool, icon=t.icon if t else "", args=act.args)
            self.emit("tool_end", name=act.tool, result=res, ok=not failed)
            spoken.append(_spoken(res.split(":", 1)[-1].strip() if failed else res))
        log.info("Commands %s done in %.2fs", [a.tool for a in acts], time.time() - t0)
        asyncio.ensure_future(self._refresh_awareness(media=any(a.tool in ("media_control", "play_youtube", "browser_video") for a in acts)))
        await self._say_simple(" ".join(spoken), text)
        return True

    async def _run_tool(self, name: str, args: dict) -> str:
        t = T.REGISTRY.get(name)
        self.emit("tool_start", name=name, label=t.label if t else name, icon=t.icon if t else "⚡", args=args)
        res = await asyncio.to_thread(T.call_tool, name, args)
        self.emit("tool_end", name=name, result=res, ok=not res.startswith("Error"))
        return res

    async def _say_simple(self, reply: str, user_text: str, store: bool = True, follow: bool = True):
        self.emit("reply_start")
        self.emit("reply_delta", text=reply)
        self.emit("reply_end", text=reply)
        self._set_state("SPEAKING")
        await self.speaker.speak(reply)
        if store:
            self.memory.add_turn(user_text, reply)
        if follow:
            self._after_speaking(getattr(self, "_voice_turn", True))
        else:
            self._set_state("STANDBY")

    def _after_speaking(self, voice: bool):
        if self.hub:
            self.hub.flush()  # drop our own voice from the mic buffer
        if voice and self.s.follow_up_seconds > 0 and not self.muted:
            self.awake_until = time.time() + self.s.follow_up_seconds
            self._set_state("LISTENING")
        else:
            self._set_state("MUTED" if self.muted else "STANDBY")

    # ── timers ─────────────────────────────────────────────────────────
    def _schedule_threadsafe(self, delay: float, label: str, kind: str) -> str:
        fut = asyncio.run_coroutine_threadsafe(self._schedule(delay, label, kind), self.loop)
        return fut.result(timeout=5)

    async def _schedule(self, delay: float, label: str, kind: str) -> str:
        tid = next(self._tid)
        due = time.time() + delay
        handle = self.loop.call_later(delay, lambda: asyncio.ensure_future(self._fire(tid)))
        self.timers[tid] = {"handle": handle, "due": due, "label": label, "kind": kind}
        self.emit("timers", items=self._timer_items())
        when = time.strftime("%I:%M %p", time.localtime(due)).lstrip("0")
        return f"{kind.title()} set: '{label}' — goes off at {when} (in {T._fmt_dur(delay)})."

    async def _fire(self, tid: int):
        t = self.timers.pop(tid, None)
        if not t:
            return
        self._fired = (getattr(self, "_fired", []) + [(t["kind"], t["label"], time.time())])[-5:]
        self.emit("timers", items=self._timer_items())
        self.emit("timer", label=t["label"], kind=t["kind"])
        msg = (f"{self.s.user_name}, your {t['label']} timer is done." if t["kind"] == "timer"
               else f"Reminder, {self.s.user_name}: {t['label']}.")
        while self._busy():
            await asyncio.sleep(0.5)
        self.player.play(CHIME_ALARM, 24000)
        await asyncio.sleep(1.8)
        self.emit("reply_start")
        self.emit("reply_delta", text="⏰ " + msg)
        self.emit("reply_end", text=msg)
        self._set_state("SPEAKING")
        await self.speaker.speak(msg)
        self._after_speaking(True)

    def _timer_items(self):
        return [{"id": k, "label": v["label"], "kind": v["kind"], "due": v["due"]} for k, v in sorted(self.timers.items(), key=lambda kv: kv[1]["due"])]

    def _list_timers(self) -> str:
        now = time.time()
        at = lambda ts: time.strftime("%I:%M %p", time.localtime(ts)).lstrip("0")
        live = [f"your {v['label']} {v['kind']} goes off in {T._fmt_dur(v['due'] - now)}, at {at(v['due'])}"
                for v in sorted(self.timers.values(), key=lambda v: v["due"])]
        done = [f"your {lab} {kind} already went off at {at(ts)}" for kind, lab, ts in getattr(self, "_fired", [])
                if now - ts < 900]
        if not live and not done:
            return "You have no timers or reminders set right now."
        parts = (["It's still set: " + "; ".join(live)] if live else []) + ([(lambda x: x[:1].upper() + x[1:])("; ".join(done))] if done else [])
        return ". ".join(parts) + "."

    def _cancel_timer_threadsafe(self, which: str) -> str:
        fut = asyncio.run_coroutine_threadsafe(self._cancel_timer(which), self.loop)
        return fut.result(timeout=5)

    async def _cancel_timer(self, which: str) -> str:
        w = which.lower().strip()
        hits = [k for k, v in self.timers.items() if w in ("all", "every", "everything") or w in v["label"].lower() or w in v["kind"]]
        if not hits and len(self.timers) == 1:
            hits = list(self.timers)
        for k in hits:
            self.timers.pop(k)["handle"].cancel()
        self.emit("timers", items=self._timer_items())
        return f"Cancelled {len(hits)}." if hits else "No matching timer."

    def cancel_timer_id(self, tid: int):
        def _c():
            t = self.timers.pop(tid, None)
            if t:
                t["handle"].cancel()
            self.emit("timers", items=self._timer_items())

        self._call(_c)


def _spoken(result: str) -> str:
    """Turn a tool result into a short spoken confirmation."""
    r = result.strip().splitlines()[0]
    m = re.search(r"NOT DONE YET\. Ask the user exactly: '(.+?)'", r)
    if m:  # power needs a yes – say the question, not the instruction meant for the AI
        return m.group(1)
    r = r.replace("Opened https://", "Opened ").replace("'", "")
    if len(r) > 320:
        cut = r.rfind(". ", 0, 320)
        r = r[: cut + 1] if cut > 80 else r[:317] + "…"
    return r


def _friendly_error(e: Exception) -> str:
    s = str(e).lower()
    if "api key" in s or "api_key" in s or "permission" in s or "401" in s or "403" in s:
        return "My API key was rejected. Check it in Settings."
    if "quota" in s or "429" in s or "rate" in s or "exhausted" in s:
        return "I've hit the model's rate limit. Give it a minute, or switch models in Settings."
    if "connect" in s or "timeout" in s or "network" in s or "getaddrinfo" in s or "resolve" in s:
        return "I can't reach the internet right now."
    if "not found" in s or "404" in s:
        return "That model name wasn't found. Pick another model in Settings."
    if "xml syntax" in s or "closed by" in s:
        return "That got too long to type out. Ask me to save it as a file instead, like: write it into a file on the desktop."
    return "Something went wrong on my side. Try that again?"
