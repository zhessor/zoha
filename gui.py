"""
Zoha — desktop app (PySide6).

    python gui.py

Keys: Space / Ctrl+Alt+Z (global, Windows) = talk · Esc = stop Zoha · Ctrl+, = settings
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Optional

from PySide6.QtCore import QSize, QTimer, Qt, Slot
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QPushButton, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget

from zoha.config import ENV_KEYS, load_settings, save_env
from zoha.logsetup import setup_logging

from zoha.ui.widgets import Backdrop, Bridge, Conversation, Dot, EmptyState, SystemLine, ToolLine, UserLine, ZohaReply, _esc
from zoha.ui.theme import CORAL, FAINT, LINE, MINT, MUTED, STATE_COPY, STYLE, TEAL, TEXT, line_icon, load_fonts, make_icon, serif_font, ui_font
from zoha.ui.settings_dialog import SettingsDialog


log = logging.getLogger("zoha.gui")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.setWindowTitle(self.settings.assistant_name)
        self.setWindowIcon(make_icon())
        self.resize(1280, 820)
        self.setMinimumSize(560, 520)
        self.setStyleSheet(STYLE)

        self.state = "BOOTING"
        self.reply: Optional[ZohaReply] = None
        self.tool_rows = {}
        self.empty: Optional[EmptyState] = None
        self.info = {}
        self._really_quit = False
        self.tray = None
        self._hotkey = False

        self._build()
        self._shortcuts()
        self._tray()

        from zoha.engine import ZohaEngine

        self.bridge = Bridge()
        self.bridge.event.connect(self._on_event)
        self.engine = ZohaEngine(self.settings, self.bridge)
        self.engine.start()
        self._register_hotkey()
        self._dark_titlebar()
        QApplication.instance().focusChanged.connect(self._focus_changed)

    def _focus_changed(self, old, new):
        bar = self.input.parentWidget()
        bar.setProperty("focus", "true" if new is self.input else "false")
        bar.style().unpolish(bar)
        bar.style().polish(bar)

    def _dark_titlebar(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            dwm = ctypes.windll.dwmapi
            on = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)  # immersive dark mode
            color = ctypes.c_uint(0x0015170F)  # caption = ground #0F1715 (COLORREF 0x00BBGGRR)
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), 4)  # Windows 11 caption colour
            text = ctypes.c_uint(0x00E3EAEC)
            dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text), 4)
        except Exception:
            pass

    # ── layout ────────────────────────────────────────────────────────
    def _build(self):
        root = Backdrop()
        self.backdrop = root
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ── header: serif wordmark, quiet status, icons ────────
        head = QWidget()
        head.setObjectName("clear")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(40, 18, 30, 8)
        hl.setSpacing(10)
        name = QLabel(self.settings.assistant_name)
        name.setFont(serif_font(24))
        name.setStyleSheet(f"color:{TEXT};")
        self.header_mark = Dot(6)
        self.presence = QLabel("")
        self.presence.hide()
        self.engine_info = QLabel("starting…")
        self.engine_info.setFont(ui_font(8.5))
        self.engine_info.setStyleSheet(f"color:{FAINT};")
        self.brain_info = QLabel("")
        self.brain_info.setFont(ui_font(8.5))
        self.brain_info.setStyleSheet(f"color:{FAINT};")
        self.brain_info.hide()
        hl.addWidget(name)
        hl.addSpacing(14)
        hl.addWidget(self.engine_info)
        hl.addWidget(self.brain_info)
        hl.addStretch(1)
        self.timers_box = QHBoxLayout()
        self.timers_box.setSpacing(6)
        hl.addLayout(self.timers_box)
        self.btn_new = QToolButton()
        self.btn_new.setIcon(line_icon("new"))
        self.btn_new.setToolTip("New chat – clears the conversation (Ctrl+N)")
        self.btn_new.clicked.connect(self._new_chat)
        self.btn_mute = QToolButton()
        self.btn_mute.setIcon(line_icon("mic"))
        self.btn_mute.setToolTip("Microphone on – click to turn it off (Ctrl+M)")
        self.btn_mute.clicked.connect(self._toggle_mute)
        self.btn_settings = QToolButton()
        self.btn_settings.setIcon(line_icon("settings"))
        self.btn_settings.setToolTip("Settings (Ctrl+,)")
        self.btn_settings.clicked.connect(self._open_settings)
        for b in (self.btn_new, self.btn_mute, self.btn_settings):
            b.setObjectName("icon")
            b.setIconSize(QSize(20, 20))
            b.setFocusPolicy(Qt.TabFocus)
            b.setCursor(Qt.PointingHandCursor)
            hl.addWidget(b)
        v.addWidget(head)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        v.addLayout(body, 1)

        # ── left: the greeting and Zoha's state (wide windows) ───
        self.pane = QWidget()
        self.pane.setObjectName("clear")
        self.pane.setFixedWidth(420)
        pl = QVBoxLayout(self.pane)
        pl.setContentsMargins(40, 34, 20, 30)
        pl.setSpacing(0)
        hour = time.localtime().tm_hour
        part = "morning" if 5 <= hour < 12 else "afternoon" if hour < 17 else "evening"
        first = (self.settings.user_name or "").strip().split(" ")[0]
        self.greeting = QLabel(f"<div style='line-height:88%'>Good {part},<br><i>{_esc(first)}.</i></div>" if first else f"Good {part}.")
        self.greeting.setTextFormat(Qt.RichText)
        self.greeting.setFont(serif_font(44))
        self.greeting.setStyleSheet(f"color:{TEXT};")
        pl.addWidget(self.greeting)
        pl.addSpacing(26)
        srow = QHBoxLayout()
        srow.setSpacing(6)
        self.state_dot = Dot(7)
        self.state_dot.setCursor(Qt.PointingHandCursor)
        self.state_dot.clicked.connect(self._talk)
        self.state_title = QLabel("Starting up")
        self.state_title.setFont(ui_font(10, QFont.Medium))
        srow.addWidget(self.state_dot)
        srow.addWidget(self.state_title)
        srow.addStretch(1)
        pl.addLayout(srow)
        pl.addSpacing(4)
        self.state_hint = QLabel("")
        self.state_hint.setFont(ui_font(10))
        self.state_hint.setStyleSheet(f"color:{MUTED};")
        self.state_hint.setWordWrap(True)
        pl.addWidget(self.state_hint)
        pl.addSpacing(6)
        self.caption = QLabel("")
        self.caption.setFont(ui_font(9.5))
        self.caption.setStyleSheet(f"color:{MINT};")
        self.caption.setFixedHeight(22)
        pl.addWidget(self.caption)
        pl.addStretch(1)
        keys = QLabel("Space to talk&nbsp;&nbsp;&nbsp;&nbsp;Esc to stop&nbsp;&nbsp;&nbsp;&nbsp;Ctrl+Alt+Z from any app")
        keys.setTextFormat(Qt.RichText)
        keys.setFont(ui_font(8.5))
        keys.setStyleSheet(f"color:{FAINT};")
        pl.addWidget(keys)
        pl.addSpacing(110)  # stay clear of the horizon
        body.addWidget(self.pane)
        self.pane_rule = QFrame()
        self.pane_rule.hide()
        # the voice (mic/output levels) drives the horizon
        self.orb = root

        # ── conversation ─────────────────────────────────────────
        right = QWidget()
        right.setObjectName("clear")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 40, 0)
        rl.setSpacing(0)
        self.conv = Conversation()
        self.conv.viewport().setAutoFillBackground(False)
        rl.addWidget(self.conv, 1)
        self.empty = EmptyState(self.settings.wake_word)
        self.empty.pick.connect(self._send)
        self.conv.add(self.empty, fade=False)
        rl.addSpacing(70)  # the horizon runs here
        body.addWidget(right, 1)

        # ── the dock: floats just under the horizon ─────────────
        dock = QWidget()
        dock.setObjectName("clear")
        dl = QHBoxLayout(dock)
        dl.setContentsMargins(0, 0, 0, 34)
        inner = QWidget()
        inner.setObjectName("clear")
        inner.setMaximumWidth(760)
        il = QVBoxLayout(inner)
        il.setContentsMargins(20, 0, 20, 0)
        il.setSpacing(8)

        self.mini = QWidget()  # compact state row (narrow windows)
        self.mini.setObjectName("clear")
        ml = QHBoxLayout(self.mini)
        ml.setContentsMargins(8, 0, 0, 0)
        ml.setSpacing(6)
        self.mini_orb = Dot(7)
        self.mini_orb.clicked.connect(self._talk)
        self.mini_title = QLabel("")
        self.mini_title.setFont(ui_font(10, QFont.Medium))
        self.mini_hint = QLabel("")
        self.mini_hint.setFont(ui_font(9.5))
        self.mini_hint.setStyleSheet(f"color:{MUTED};")
        ml.addWidget(self.mini_orb)
        ml.addWidget(self.mini_title)
        ml.addSpacing(6)
        ml.addWidget(self.mini_hint)
        ml.addStretch(1)
        il.addWidget(self.mini)

        bar = QWidget()
        bar.setObjectName("inputbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(24, 7, 8, 7)
        bar.setFixedHeight(58)
        bl.setSpacing(8)
        self.input = QLineEdit()
        self.input.setObjectName("input")
        self.input.setFont(ui_font(11))
        self.input.setPlaceholderText("Ask Zoha anything…")
        self.input.returnPressed.connect(self._send_input)
        self.input.textChanged.connect(lambda t: self.btn_send.setVisible(bool(t.strip())))
        self.btn_send = QToolButton()
        self.btn_send.setObjectName("send")
        self.btn_send.setIcon(line_icon("send", TEXT))
        self.btn_send.setIconSize(QSize(20, 20))
        self.btn_send.setToolTip("Send (Enter)")
        self.btn_send.setCursor(Qt.PointingHandCursor)
        self.btn_send.clicked.connect(self._send_input)
        self.btn_send.setFocusPolicy(Qt.TabFocus)
        self.btn_send.hide()
        self.btn_talk = QToolButton()
        self.btn_talk.setObjectName("talk")
        self.btn_talk.setIcon(line_icon("mic", MINT))
        self.btn_talk.setIconSize(QSize(20, 20))
        self.btn_talk.setCursor(Qt.PointingHandCursor)
        self.btn_talk.setToolTip("Talk without saying the wake word (Space, or Ctrl+Alt+Z anywhere)")
        self.btn_talk.clicked.connect(self._talk)
        self.btn_talk.setFocusPolicy(Qt.TabFocus)
        bl.addWidget(self.input, 1)
        bl.addWidget(self.btn_send)
        bl.addWidget(self.btn_talk)
        il.addWidget(bar)
        dl.addStretch(1)
        dl.addWidget(inner, 100)
        dl.addStretch(1)
        v.addWidget(dock)

        self._apply_state("BOOTING")
        self._layout_mode()
        self.input.setFocus()

    def _rule(self, vertical: bool = False) -> QFrame:
        f = QFrame()
        if vertical:
            f.setFixedWidth(1)
        else:
            f.setFixedHeight(1)
        f.setStyleSheet(f"background:{LINE};")
        return f

    def _layout_mode(self):
        wide = self.width() >= 1080
        self.pane.setVisible(wide)
        self.pane_rule.setVisible(False)
        self.mini.setVisible(not wide)
        if self.empty is not None:  # the greeting lives on the left in wide windows
            self.empty.hello.setVisible(not wide)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "pane"):
            self._layout_mode()

    def _shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._stop)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self._open_settings)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self._toggle_mute)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._new_chat)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: self.input.setFocus())

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Space, Qt.Key_F8) and not self.input.hasFocus():
            self._talk()
            return
        if not self.input.hasFocus() and e.text() and e.text().isprintable() and not e.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            self.input.setFocus()
            self.input.insert(e.text())
            return
        super().keyPressEvent(e)

    def _tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip("Zoha")
        m = QMenu()
        m.addAction("Show Zoha", self._show)
        m.addAction("Talk", self._talk)
        self.act_mute = m.addAction("Turn mic off", self._toggle_mute)
        m.addSeparator()
        m.addAction("Quit", self._quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self._show() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    # ── Windows global hotkey (Ctrl+Alt+Z) ───────────────────────────
    def _register_hotkey(self):
        self._hotkey = False
        if sys.platform != "win32":
            return
        try:
            import ctypes

            MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
            self._hotkey = bool(ctypes.windll.user32.RegisterHotKey(int(self.winId()), 1, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, 0x5A))
        except Exception as e:
            log.warning("Global hotkey unavailable: %s", e)

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32" and self._hotkey and bytes(eventType) == b"windows_generic_MSG":
            try:
                import ctypes.wintypes

                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0312 and msg.wParam == 1:
                    self._talk()
                    return True, 0
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    # ── actions ──────────────────────────────────────────────────────
    def _talk(self):
        self.engine.push_to_talk()

    def _stop(self):
        self.engine.interrupt()

    def _send_input(self):
        t = self.input.text().strip()
        if t:
            self.input.clear()
            self._send(t)

    def _send(self, text: str):
        self.engine.send_text(text)

    def _new_chat(self):
        self.engine.clear_memory()
        self.conv.clear_all()
        self.reply = None
        self.empty = EmptyState(self.settings.wake_word)
        self.empty.pick.connect(self._send)
        self.conv.add(self.empty)

    def _toggle_mute(self):
        self.engine.set_muted(self.state != "MUTED")

    def _open_settings(self):
        from zoha.audio import list_input_devices

        dlg = SettingsDialog(self.settings, list_input_devices(), self)
        dlg.preview.clicked.connect(lambda: self._preview_voice(dlg))
        if dlg.exec() != QDialog.Accepted:
            return
        vals = dlg.values()
        old = {k: getattr(self.settings, k) for k in vals}
        save_env({ENV_KEYS[k]: v for k, v in vals.items()})
        voice_only = {"tts_voice", "tts_rate", "kokoro_voice", "kokoro_speed"}
        changed = {k for k in vals if vals[k] != old[k]}
        for k in voice_only & changed:
            setattr(self.settings, k, vals[k])
        if "tts_voice" in changed:
            self.engine.set_voice(vals["tts_voice"])
        for k in ("kokoro_voice", "kokoro_speed"):
            setattr(self.engine.s, k, vals[k])
        if changed - voice_only:
            self._restart()
        else:
            self.conv.add(SystemLine("Voice updated."))

    def _preview_voice(self, dlg):
        self.settings.tts_rate = f"{dlg.rate.value():+d}%"
        self.engine.set_voice(dlg.voice.currentData())
        self.engine.send_text("Introduce yourself in one short sentence.") if self.settings.llm_ready() else None

    def _restart(self):
        self.engine.shutdown()
        time.sleep(0.4)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _show(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self):
        self._really_quit = True
        self.close()

    def closeEvent(self, e):
        if self.tray and not self._really_quit and os.getenv("ZOHA_CLOSE_TO_TRAY", "1") == "1":
            e.ignore()
            self.hide()
            self.tray.showMessage("Zoha is still listening", "Say “%s” anytime. Right-click the tray icon to quit." % self.settings.wake_word.title(),
                                  make_icon(), 2500)
            return
        try:
            if sys.platform == "win32" and self._hotkey:
                import ctypes

                ctypes.windll.user32.UnregisterHotKey(int(self.winId()), 1)
        except Exception:
            pass
        self.engine.shutdown()
        e.accept()
        QApplication.instance().quit()

    # ── engine events ────────────────────────────────────────────────
    def _drop_empty(self):
        if self.empty is not None:
            self.empty.deleteLater()
            self.conv.v.removeWidget(self.empty)
            self.empty = None

    def _apply_state(self, st: str):
        self.state = st
        wake = self.settings.wake_word.title()
        title, hint = STATE_COPY.get(st, (st.title(), ""))
        self.state_title.setText(title.format(wake=wake))
        self.state_hint.setText(hint.format(wake=wake))
        col = {"LISTENING": MINT, "SPEAKING": MINT, "THINKING": TEAL, "MUTED": CORAL, "STANDBY": TEAL}.get(st, MUTED)
        self.state_title.setStyleSheet(f"color:{col};")
        self.state_dot.set_state(st)
        self.mini_title.setText(title.format(wake=wake))
        self.mini_title.setStyleSheet(f"color:{col};")
        self.mini_hint.setText(hint.format(wake=wake))
        self.mini_orb.set_state(st)
        self.presence.setStyleSheet(f"color:{ {'LISTENING': MINT, 'SPEAKING': MINT, 'THINKING': TEAL, 'MUTED': CORAL, 'STANDBY': TEAL}.get(st, FAINT) };")
        self.orb.set_state(st)
        live = st in ("LISTENING", "SPEAKING")
        self.btn_talk.setProperty("live", "true" if live else "false")
        self.btn_talk.setIcon(line_icon("stop" if st in ("SPEAKING", "THINKING") else "mic", MINT))
        self.btn_talk.setToolTip("Stop (Esc)" if st in ("SPEAKING", "THINKING") else
                                 "Talk without saying the wake word (Space, or Ctrl+Alt+Z anywhere)")
        self.header_mark.set_state(st)
        try:
            self.btn_talk.clicked.disconnect()
        except Exception:
            pass
        self.btn_talk.clicked.connect(self._stop if st in ("SPEAKING", "THINKING") else self._talk)
        self.btn_talk.style().unpolish(self.btn_talk)
        self.btn_talk.style().polish(self.btn_talk)
        self.btn_mute.setIcon(line_icon("mic_off", CORAL) if st == "MUTED" else line_icon("mic"))
        self.btn_mute.setToolTip("Microphone off – click to turn it on (Ctrl+M)" if st == "MUTED"
                                 else "Microphone on – click to turn it off (Ctrl+M)")
        self.btn_mute.setProperty("on", "true" if st == "MUTED" else "false")
        self.btn_mute.style().unpolish(self.btn_mute)
        self.btn_mute.style().polish(self.btn_mute)
        if self.tray:
            self.tray.setToolTip(f"Zoha: {title.format(wake=wake).lower()}")
            self.act_mute.setText("Turn mic on" if st == "MUTED" else "Turn mic off")
        if st != "LISTENING":
            self.caption.setText("")

    @Slot(str, dict)
    def _on_event(self, ev: str, d: dict):
        if ev == "state":
            self._apply_state(d["state"])
        elif ev == "mic_level":
            self.orb.mic = self.mini_orb.mic = d["level"]
        elif ev == "out_level":
            self.orb.out = self.mini_orb.out = d["level"]
        elif ev == "hearing":
            self.caption.setText("hearing you…" if d.get("active") else "")
        elif ev == "overheard":
            pass
        elif ev == "woke":
            self._show_if_hidden_hint()
        elif ev == "user":
            self._drop_empty()
            self.conv.add(UserLine(d["text"], d.get("modality", "voice")))
            self.reply = None
        elif ev == "reply_start":
            self._drop_empty()
            self.reply = None
        elif ev == "reply_delta":
            if self.reply is None:
                self.reply = self.conv.add(ZohaReply())
            self.reply.append(d["text"])
        elif ev == "reply_end":
            if self.reply is not None and d.get("text"):
                self.reply.set_text(self.reply.text or d["text"])
            self.reply = None
        elif ev == "tool_start":
            self._drop_empty()
            row = self.conv.add(ToolLine(d.get("icon", "⚡"), d.get("label", d["name"]), d.get("args") or {}))
            self.tool_rows.setdefault(d["name"], []).append(row)
            self.reply = None
        elif ev == "tool_end":
            rows = self.tool_rows.get(d["name"]) or []
            if rows:
                rows.pop(0).finish(d.get("result", ""), d.get("ok", True))
        elif ev == "info":
            self.conv.add(SystemLine(d["text"]))
        elif ev == "error":
            self.conv.add(SystemLine(d["text"], error=True))
        elif ev == "ready":
            self.info = d
            words = " / ".join(w.title() for w in d.get("wake_words", []))
            gpu = "GPU" in str(d.get("stt"))
            self.engine_info.setText(f"<span style='color:{MINT if gpu else MUTED}'>●</span>&nbsp; {d.get('stt')}")
            self.brain_info.setText(f"<span style='color:{TEAL if d.get('brain') != 'no API key' else CORAL}'>●</span>&nbsp; {d.get('brain')}")
            self.brain_info.show()
            self.engine_info.setToolTip(f"Speech: {d.get('stt')} (wake pass: {d.get('wake')})\nGPU: {d.get('gpu')}\nBrain: {d.get('brain')}\nVoice: {d.get('voice')}\nWake words: {words}")
        elif ev == "brain":
            local = "(local)" in str(d.get("name"))
            self.brain_info.setText(f"<span style='color:{MINT if local else TEAL}'>●</span>&nbsp; {d.get('name')}")
            self.brain_info.setToolTip("Answered by your local model on the GPU (unlimited, offline)" if local
                                       else "Answered by Gemini")
        elif ev == "timers":
            self._render_timers(d.get("items", []))
        elif ev == "timer":
            self._show()
            if self.tray:
                self.tray.showMessage("Zoha", ("Timer done: " if d["kind"] == "timer" else "Reminder: ") + d["label"], make_icon(), 8000)
        elif ev == "interrupted":
            self.reply = None
        elif ev == "exit":
            self._quit()

    def _show_if_hidden_hint(self):
        if self.tray and self.isHidden():
            self.tray.showMessage("Zoha", "Listening…", make_icon(MINT), 1500)

    def _render_timers(self, items):
        while self.timers_box.count():
            w = self.timers_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._timer_items = items
        for it in items:
            b = QPushButton()
            b.setObjectName("timer")
            b.setFont(ui_font(9))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"{it['kind'].title()}: {it['label']}. Click to cancel.")
            b.clicked.connect(lambda _=False, tid=it["id"]: self.engine.cancel_timer_id(tid))
            b.setProperty("due", it["due"])
            b.setProperty("label", it["label"])
            self.timers_box.addWidget(b)
        self._tick_timers()
        if items and not hasattr(self, "_tt"):
            self._tt = QTimer(self)
            self._tt.timeout.connect(self._tick_timers)
            self._tt.start(1000)

    def _tick_timers(self):
        for i in range(self.timers_box.count()):
            b = self.timers_box.itemAt(i).widget()
            if not b:
                continue
            left = max(0, int(b.property("due") - time.time()))
            h, r = divmod(left, 3600)
            m, s = divmod(r, 60)
            label = str(b.property("label"))[:18]
            b.setText(f"⏱ {label}  {f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'}")


def main():
    setup_logging()
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Zhessor.Zoha")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Zoha")

    # one Zoha at a time: a second launch just brings the running one to the front
    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    key = "zhessor-zoha-single-instance"
    probe = QLocalSocket()
    probe.connectToServer(key)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        print("Zoha is already running – brought it to the front.")
        sys.exit(0)
    QLocalServer.removeServer(key)  # clean up after a crash
    server = QLocalServer()
    server.listen(key)
    app.setQuitOnLastWindowClosed(False)
    load_fonts()
    app.setFont(ui_font(10))
    w = MainWindow()
    w.show()
    server.newConnection.connect(lambda: (server.nextPendingConnection(), w._show()))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
