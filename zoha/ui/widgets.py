"""Zoha's building blocks: the orb, status mark, conversation lines, the empty state and the animated backdrop."""

from __future__ import annotations

import math
import os
import time

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QPropertyAnimation, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from zoha.ui.theme import CORAL, FAINT, GROUND, MINT, MUTED, TEAL, TEXT, serif_font, ui_font


# ── Engine → Qt bridge ───────────────────────────────────────────────────────
class Bridge(QObject):
    event = Signal(str, dict)

    def __call__(self, _event, **data):
        self.event.emit(_event, data)


# ── The orb (signature element) ──────────────────────────────────────────────
class Orb(QWidget):
    """
    Zoha's presence – a hairline ring around a soft teal core (the Zhessor mark language).
      booting   – the ring draws itself once
      standby   – quiet, the core breathes slowly
      listening – the ring becomes your voice's waveform
      thinking  – one light arc moves slowly around the ring
      speaking  – the ring follows Zoha's own voice
      muted     – grey, dashed, still
    Click to talk.
    """

    clicked = Signal()

    def __init__(self, diameter: int = 280, parent=None):
        super().__init__(parent)
        self.d = diameter
        self.small = diameter < 80
        side = int(diameter * (1.18 if self.small else 1.42))
        self.setFixedSize(side, side)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to talk")
        self.state = "BOOTING"
        self.mic = 0.0
        self.out = 0.0
        self.level = 0.0
        self.t = 0.0
        self.spin = 0.0
        self.glow = 0.0
        self.draw_in = 0.0
        self.reduced = os.getenv("ZOHA_REDUCED_MOTION", "") == "1"
        if self.reduced:
            self.draw_in = 1.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_state(self, st):
        self.state = st

    def _tick(self):
        target = {"LISTENING": self.mic, "SPEAKING": self.out, "STANDBY": self.mic * 0.2}.get(self.state, 0.0)
        self.level += (target - self.level) * (0.32 if target > self.level else 0.10)
        g_target = {"LISTENING": 1.0, "SPEAKING": 0.9, "THINKING": 0.7, "STANDBY": 0.4, "BOOTING": 0.15}.get(self.state, 0.1)
        self.glow += (g_target - self.glow) * 0.05
        if self.draw_in < 1.0:
            self.draw_in = min(1.0, self.draw_in + 0.012)  # one soft draw-in (~1.4 s)
        if not self.reduced:
            self.t += 0.016 * (1.0 + self.level * 2.5)
            self.spin = (self.spin + (1.4 if self.state == "THINKING" else 0.0)) % 360
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        R = self.d / 2
        muted = self.state in ("MUTED",)
        dim = self.state == "BOOTING"
        ease = 1 - (1 - self.draw_in) ** 3

        # corner brackets (static, very faint) – only on the big presence
        if not self.small:
            br = QColor(MUTED)
            br.setAlpha(int(46 * ease))
            pen = QPen(br, 1)
            p.setPen(pen)
            box = R * 1.2
            arm = R * 0.13
            for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                x, y = c.x() + sx * box, c.y() + sy * box
                p.drawLine(QPointF(x, y), QPointF(x - sx * arm, y))
                p.drawLine(QPointF(x, y), QPointF(x, y - sy * arm))

        # soft core: a teal glow inside the ring, breathing gently
        breathe = 0.0 if self.reduced else math.sin(self.t * 1.1) * 0.03
        core_r = R * (0.70 + breathe + self.level * 0.10)
        core = QRadialGradient(c, core_r)
        if muted or dim:
            core.setColorAt(0.0, QColor(90, 110, 104, 70 if muted else 40))
            core.setColorAt(1.0, QColor(0, 0, 0, 0))
        else:
            a = int(70 + 120 * self.glow)
            core.setColorAt(0.0, QColor(110, 245, 238, a))
            core.setColorAt(0.35, QColor(92, 211, 195, int(a * 0.55)))
            core.setColorAt(0.75, QColor(2, 86, 76, int(a * 0.30)))
            core.setColorAt(1.0, QColor(2, 86, 76, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(core)
        p.drawEllipse(c, core_r, core_r)

        # the ring: a hairline that becomes the voice waveform
        n = 160
        amp = R * (0.0 if muted else (0.004 + self.level * 0.085))
        path = QPainterPath()
        sweep = ease  # draws itself once on start
        for i in range(int(n * sweep) + 1):
            a = -math.pi / 2 + 2 * math.pi * i / n
            w = (math.sin(4 * a + self.t * 2.4) * 0.55 + math.sin(7 * a - self.t * 1.9) * 0.30
                 + math.sin(11 * a + self.t * 3.3) * 0.15)
            r = R + amp * w
            pt = QPointF(c.x() + r * math.cos(a), c.y() + r * math.sin(a))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        if sweep >= 1.0:
            path.closeSubpath()
        rc = QColor(FAINT if (muted or dim) else TEAL)
        rc.setAlpha(int(110 + 120 * (0 if muted else self.glow)) if not dim else 120)
        pen = QPen(rc, 1.6 if self.small else 1.3)
        if muted:
            pen.setDashPattern([3, 4])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        # thinking: one light arc travelling slowly around the ring
        if self.state == "THINKING":
            arc = QPen(QColor(MINT), 2.2 if self.small else 2.0)
            arc.setCapStyle(Qt.RoundCap)
            p.setPen(arc)
            rect = QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R)
            p.drawArc(rect, int((90 - self.spin) * 16), int(-48 * 16))
        p.end()


class StatusMark(QWidget):
    """Small drawn status for tool rows: spinning arc → check / cross."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.mode = "busy"
        self.a = 0
        self._t = QTimer(self)
        self._t.timeout.connect(self._spin)
        self._t.start(16)

    def _spin(self):
        self.a = (self.a + 8) % 360
        self.update()

    def done(self, ok: bool):
        self.mode = "ok" if ok else "fail"
        self._t.stop()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(2, 2, 14, 14)
        if self.mode == "busy":
            pen = QPen(QColor(TEAL), 1.8)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(r, -self.a * 16, 270 * 16)
        else:
            col = QColor(TEAL if self.mode == "ok" else CORAL)
            fill = QColor(col)
            fill.setAlpha(40)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawEllipse(r)
            pen = QPen(col, 1.8)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            if self.mode == "ok":
                path = QPainterPath(QPointF(5.5, 9.2))
                path.lineTo(8.0, 11.6)
                path.lineTo(12.6, 6.6)
                p.drawPath(path)
            else:
                p.drawLine(QPointF(6.5, 6.5), QPointF(11.5, 11.5))
                p.drawLine(QPointF(11.5, 6.5), QPointF(6.5, 11.5))
        p.end()


# ── Conversation widgets ─────────────────────────────────────────────────────
class UserLine(QWidget):
    def __init__(self, text: str, modality: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 10, 0, 2)
        lay.addStretch(1)
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lab.setFont(ui_font(10.5))
        lab.setStyleSheet(f"background:rgba(255,255,255,15); color:{TEXT}; border:none; border-radius:18px;"
                          f" border-bottom-right-radius:5px; padding:11px 17px;")
        lab.setMaximumWidth(520)
        natural = lab.fontMetrics().horizontalAdvance(text) + 30
        lab.setMinimumWidth(min(520, natural))
        lab.setToolTip("Heard by voice" if modality == "voice" else "Typed")
        lay.addWidget(lab, 0, Qt.AlignRight)


class ToolLine(QWidget):
    def __init__(self, icon: str, label: str, args: dict):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 3, 60, 3)
        lay.setSpacing(10)
        lay.setContentsMargins(0, 6, 0, 2)
        self.mark = StatusMark()
        detail = ", ".join(str(v) for v in args.values() if v not in (None, "", False))[:70]
        self.lab = QLabel(f"<span style='color:{MUTED}'>{label}</span>"
                          f"{('<span style=\'color:' + FAINT + '\'>  ' + _esc(detail) + '</span>') if detail else ''}")
        self.lab.setFont(ui_font(9.5))
        self.res = QLabel("")
        self.res.setFont(ui_font(9.5))
        self.res.setStyleSheet(f"color:{FAINT};")
        self.res.setWordWrap(True)
        lay.addWidget(self.mark, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(self.lab)
        col.addWidget(self.res)
        lay.addLayout(col, 1)

    def finish(self, result: str, ok: bool):
        first = result.strip().splitlines()[0] if result.strip() else ("Done" if ok else "Failed")
        if first.startswith("NOT DONE YET"):
            first = "Waiting for your yes"
        if len(first) > 120:
            first = first[:117] + "…"
        self.mark.done(ok)
        self.res.setText(first)
        self.res.setToolTip(result[:2000])
        self.res.setStyleSheet(f"color:{MUTED if ok else CORAL};")


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class ZohaReply(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 10, 40, 4)
        lay.setSpacing(5)
        self.setToolTip(f"Zoha · {time.strftime('%I:%M %p').lstrip('0')}")
        self.text = ""
        self.lab = QLabel("")
        self.lab.setTextFormat(Qt.MarkdownText)
        self.lab.setWordWrap(True)
        self.lab.setOpenExternalLinks(True)
        self.lab.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.lab.setFont(ui_font(11.5))
        self.lab.setStyleSheet(f"color:{TEXT};")
        self.lab.setMaximumWidth(680)
        lay.addWidget(self.lab)
        self._dirty = False
        self._t = QTimer(self)
        self._t.setInterval(40)
        self._t.timeout.connect(self._flush)
        self._t.start()

    def append(self, delta: str):
        self.text += delta
        self._dirty = True

    def set_text(self, text: str):
        self.text = text
        self._dirty = True
        self._flush()

    def _flush(self):
        if self._dirty:
            self.lab.setText(self.text)
            self._dirty = False


class SystemLine(QLabel):
    def __init__(self, text: str, error: bool = False):
        super().__init__(text)
        self.setWordWrap(True)
        self.setFont(ui_font(9.5))
        self.setStyleSheet(f"color:{CORAL if error else FAINT}; padding:6px 2px;")


class Conversation(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("convhost")
        outer = QHBoxLayout(host)
        outer.setContentsMargins(0, 0, 0, 0)
        col = QWidget()
        col.setMaximumWidth(760)
        self.v = QVBoxLayout(col)
        self.v.setContentsMargins(28, 18, 28, 18)
        self.v.setSpacing(2)
        self.v.addStretch(1)
        outer.addStretch(1)
        outer.addWidget(col, 100)
        outer.addStretch(1)
        self.setWidget(host)
        self.verticalScrollBar().rangeChanged.connect(self._stick)
        self._follow = True
        self.verticalScrollBar().valueChanged.connect(self._track)

    def _track(self, v):
        sb = self.verticalScrollBar()
        self._follow = v >= sb.maximum() - 40

    def _stick(self, *_):
        if self._follow:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def add(self, w: QWidget, fade: bool = True):
        self._follow = True
        self.v.insertWidget(self.v.count(), w)
        if fade and os.getenv("ZOHA_REDUCED_MOTION", "") != "1":
            eff = QGraphicsOpacityEffect(w)
            w.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity", w)
            anim.setDuration(220)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(lambda: w.setGraphicsEffect(None))
            anim.start()
        return w

    def clear_all(self):
        while self.v.count() > 1:
            item = self.v.takeAt(1)
            if item.widget():
                item.widget().deleteLater()


class EmptyState(QWidget):
    pick = Signal(str)
    EXAMPLES = [
        "What's the weather in Mumbai tomorrow?",
        "Play some lofi on YouTube",
        "Open VS Code and set a 25 minute focus timer",
        "Find my resume and open it",
        "Go to Amazon and find a well-rated laptop stand under ₹1,500",
        "What's the latest news in AI?",
        "Any new enquiries on the website?",
    ]

    def __init__(self, wake: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 40, 0, 10)
        lay.setSpacing(6)
        hour = time.localtime().tm_hour
        part = "morning" if 5 <= hour < 12 else "afternoon" if hour < 17 else "evening"
        name = (os.getenv("USER_NAME") or "there").strip().split(" ")[0]
        h = QLabel(f"Good {part}{', ' + name if name else ''}.")
        h.setFont(serif_font(34))
        h.setStyleSheet(f"color:{TEXT};")
        self.hello = h
        sub = QLabel("A few things you can ask:")
        self.sub = sub
        sub.setWordWrap(True)
        sub.setFont(ui_font(10.5))
        sub.setStyleSheet(f"color:{MUTED};")
        lay.addWidget(h)
        lay.addWidget(sub)
        lay.addSpacing(22)
        for ex in self.EXAMPLES:
            b = QPushButton(ex)
            b.setObjectName("example")
            b.setCursor(Qt.PointingHandCursor)
            b.setFont(ui_font(10.5))
            b.clicked.connect(lambda _=False, t=ex: self.pick.emit(t))
            lay.addWidget(b)


class Backdrop(QWidget):
    """
    The whole window's background: deep ink, a soft teal glow rising from the bottom edge,
    and the horizon – one fine line of light above the input that moves with the voice.
      booting   – the line draws outward from the centre, once
      standby   – a slow, barely-there drift
      listening – it follows your voice
      thinking  – a single bright point travels along it
      speaking  – it follows Zoha's voice
      muted     – the glow goes out, the line turns grey and dashed
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "BOOTING"
        self.mic = self.out = self.level = 0.0
        self.glow = 0.0
        self.t = 0.0
        self.draw_in = 0.0
        self.horizon_from_bottom = 150
        self.reduced = os.getenv("ZOHA_REDUCED_MOTION", "") == "1"
        if self.reduced:
            self.draw_in = 1.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # 30 fps is plenty for a slow line – easy on the CPU/GPU

    def set_state(self, st):
        self.state = st

    def _tick(self):
        target = {"LISTENING": self.mic, "SPEAKING": self.out, "STANDBY": self.mic * 0.15}.get(self.state, 0.0)
        self.level += (target - self.level) * (0.30 if target > self.level else 0.08)
        g = {"LISTENING": 1.0, "SPEAKING": 0.9, "THINKING": 0.72, "STANDBY": 0.55, "BOOTING": 0.25, "MUTED": 0.0}.get(self.state, 0.4)
        self.glow += (min(1.0, g + self.level * 0.4) - self.glow) * 0.05
        if self.draw_in < 1.0:
            self.draw_in = min(1.0, self.draw_in + 0.025)
        if not self.reduced:
            self.t += 0.033 * (1.0 + self.level * 2.0)
        h = self.height()
        self.update(0, max(0, h - 360), self.width(), 360)  # only the bottom band changes

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(e.rect(), QColor(GROUND))
        # soft glow rising from the bottom edge
        if self.glow > 0.01:
            c = QPointF(w / 2, h + 70)
            rg = QRadialGradient(c, max(w * 0.62, 600))
            a = self.glow
            rg.setColorAt(0.0, QColor(110, 245, 238, int(95 * a)))
            rg.setColorAt(0.22, QColor(92, 211, 195, int(46 * a)))
            rg.setColorAt(0.5, QColor(2, 86, 76, int(22 * a)))
            rg.setColorAt(1.0, QColor(2, 86, 76, 0))
            p.save()
            p.translate(c)
            p.scale(1.0, 0.42)  # flatten into a wide dawn-like ellipse
            p.translate(-c)
            p.setPen(Qt.NoPen)
            p.setBrush(rg)
            p.drawEllipse(c, max(w * 0.62, 600), max(w * 0.62, 600))
            p.restore()
        # the horizon line
        y0 = h - self.horizon_from_bottom
        muted = self.state == "MUTED"
        ease = 1 - (1 - self.draw_in) ** 3
        half = w / 2 * ease
        amp = 0 if muted else (5.0 + self.level * 34.0)
        path = QPainterPath()
        steps = 140
        for i in range(steps + 1):
            x = w / 2 - half + 2 * half * i / steps
            u = x / max(1, w)
            env = math.sin(math.pi * min(1.0, max(0.0, u))) ** 1.4  # calm at the edges
            yv = (math.sin(u * 7.0 + self.t * 0.9) * 0.55 + math.sin(u * 13.0 - self.t * 1.4) * 0.30
                  + math.sin(u * 23.0 + self.t * 2.3) * 0.15 * (0.3 + self.level))
            pt = QPointF(x, y0 - amp * env * yv)
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        grad = QLinearGradient(0, 0, w, 0)
        base = QColor(FAINT if muted else MINT)
        alpha = 90 if muted else int(120 + 120 * min(1.0, self.glow))
        grad.setColorAt(0.0, QColor(base.red(), base.green(), base.blue(), 0))
        if self.state == "THINKING" and not self.reduced:
            pos = (self.t * 0.18) % 1.0  # one bright point travelling along the line
            grad.setColorAt(max(0.001, pos - 0.12), QColor(base.red(), base.green(), base.blue(), int(alpha * 0.45)))
            grad.setColorAt(pos, QColor(255, 255, 255, 235))
            grad.setColorAt(min(0.999, pos + 0.12), QColor(base.red(), base.green(), base.blue(), int(alpha * 0.45)))
        else:
            grad.setColorAt(0.5, QColor(base.red(), base.green(), base.blue(), alpha))
        grad.setColorAt(1.0, QColor(base.red(), base.green(), base.blue(), 0))
        pen = QPen(grad, 1.6)
        if muted:
            pen.setDashPattern([4, 5])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.end()


class Dot(QWidget):
    """A small state dot (header + compact layouts)."""

    clicked = Signal()

    def __init__(self, size: int = 8, parent=None):
        super().__init__(parent)
        self.setFixedSize(size + 8, size + 8)
        self.s = size
        self.state = "BOOTING"
        self.mic = self.out = 0.0

    def set_state(self, st):
        self.state = st
        self.update()

    def mousePressEvent(self, e):
        self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor({"LISTENING": MINT, "SPEAKING": MINT, "THINKING": TEAL, "MUTED": CORAL, "STANDBY": TEAL}.get(self.state, FAINT))
        c = QPointF(self.width() / 2, self.height() / 2)
        if self.state in ("LISTENING", "SPEAKING"):
            halo = QColor(col)
            halo.setAlpha(60)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(c, self.s * 0.9, self.s * 0.9)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(c, self.s / 2, self.s / 2)
        p.end()
