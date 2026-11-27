"""Zoha look and feel: colour tokens, fonts, the Qt stylesheet and icons."""

from __future__ import annotations

import math
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPen, QPixmap
from zoha.config import ROOT


# ── Zhessor dark tokens ───────────────────────────────────────────────────────
GROUND = "#080E0D"

PANE = "#0C1513"

SURFACE = "#131D1B"

SURFACE_2 = "#192522"

LINE = "#1D2A27"

TEXT = "#ECEAE3"

MUTED = "#8FA39E"

FAINT = "#5E716C"

TEAL = "#5CD3C3"

MINT = "#6EF5EE"

DEEP = "#02564C"

CORAL = "#E58B7B"


STATE_COPY = {
    "BOOTING": ("Starting up", "Getting my voice and ears ready."),
    "STANDBY": ("Ready", "Say “{wake}”, or press Space to talk."),
    "LISTENING": ("Listening", "Go ahead, I'm listening."),
    "THINKING": ("Thinking", "One moment."),
    "SPEAKING": ("Speaking", "Press Esc, or just say “{wake}”, to stop me."),
    "MUTED": ("Microphone off", "Type below, or turn the mic back on."),
}


VOICES = [
    ("en-US-JennyNeural", "Jenny (US, warm)"),
    ("en-US-AvaMultilingualNeural", "Ava (US, expressive)"),
    ("en-US-EmmaMultilingualNeural", "Emma (US, bright)"),
    ("en-GB-SoniaNeural", "Sonia (UK)"),
    ("en-GB-LibbyNeural", "Libby (UK, young)"),
    ("en-IN-NeerjaNeural", "Neerja (India)"),
    ("en-IN-NeerjaExpressiveNeural", "Neerja expressive (India)"),
    ("en-AU-NatashaNeural", "Natasha (Australia)"),
    ("en-GB-RyanNeural", "Ryan (UK, male)"),
    ("en-US-AndrewMultilingualNeural", "Andrew (US, male)"),
    ("en-IN-PrabhatNeural", "Prabhat (India, male)"),
    ("hi-IN-SwaraNeural", "Swara (Hindi)"),
]


WHISPER_MODELS = ["auto", "large-v3-turbo", "distil-large-v3", "medium.en", "small.en", "base.en", "tiny.en", "large-v3", "small"]


def ui_font(size: float, weight=QFont.Normal) -> QFont:
    fams = set(QFontDatabase.families())
    for fam in ("Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text", "Helvetica Neue", "Noto Sans", "DejaVu Sans"):
        if fam in fams:
            break
    f = QFont(fam)
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def display_font(size: float, weight=QFont.DemiBold) -> QFont:
    fams = set(QFontDatabase.families())
    for fam in ("Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans"):
        if fam in fams:
            break
    f = QFont(fam)
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


_SERIF = {"family": None}


def load_fonts():
    """Bundled display serif (Instrument Serif, SIL OFL – see assets/fonts/InstrumentSerif-OFL.txt)."""
    d = str(ROOT / "assets" / "fonts")
    for f in ("InstrumentSerif-Regular.ttf", "InstrumentSerif-Italic.ttf"):
        fid = QFontDatabase.addApplicationFont(os.path.join(d, f))
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        if fams and not _SERIF["family"]:
            _SERIF["family"] = fams[0]


def serif_font(size: float, italic: bool = False) -> QFont:
    fam = _SERIF["family"]
    if not fam:
        fams = set(QFontDatabase.families())
        fam = next((f for f in ("Instrument Serif", "Sitka Display", "Georgia", "Cambria", "DejaVu Serif") if f in fams), "serif")
    f = QFont(fam)
    f.setPointSizeF(size)
    f.setItalic(italic)
    return f


# ── Main window ──────────────────────────────────────────────────────────────
STYLE = f"""
QMainWindow {{ background:{GROUND}; }}
QWidget#convhost, QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget, QWidget#clear {{ background:transparent; }}
QWidget {{ color:{TEXT}; }}
QToolTip {{ background:{SURFACE_2}; color:{TEXT}; border:1px solid {LINE}; padding:5px 8px; }}
QWidget#pane {{ background:{PANE}; }}
QWidget#inputbar {{ background:rgba(8,14,13,190); border:1px solid rgba(110,245,238,56); border-radius:29px; }}
QWidget#inputbar[focus="true"] {{ border:1px solid rgba(110,245,238,120); background:rgba(8,14,13,215); border-radius:29px; }}
QLineEdit#input {{ background:transparent; border:none; padding:8px 0; color:{TEXT}; selection-background-color:{DEEP}; }}
QLabel#pill {{ background:{SURFACE}; border:1px solid {LINE}; border-radius:11px; padding:3px 10px; color:{MUTED}; }}
QLabel#keycap {{ background:{SURFACE}; border:1px solid {LINE}; border-bottom:2px solid {LINE}; border-radius:6px; padding:2px 8px; color:{TEXT}; }}
QToolButton#send {{ background:rgba(255,255,255,14); padding:0; border-radius:21px; min-width:42px; min-height:42px; }}
QToolButton#send:hover {{ background:#22322E; }}
QToolButton#icon {{ padding:8px; border-radius:10px; }}
QToolButton#icon:hover {{ background:{SURFACE}; }}
QToolButton {{ background:transparent; border:none; color:{MUTED}; padding:6px 8px; border-radius:8px; }}
QToolButton:hover {{ background:{SURFACE}; color:{TEXT}; }}
QToolButton:focus {{ outline:none; border:1px solid {TEAL}; }}
QToolButton#talk {{ background:rgba(110,245,238,36); border:1px solid rgba(110,245,238,128); border-radius:21px; min-width:42px; max-width:42px; min-height:42px; max-height:42px; padding:0; }}
QToolButton#talk:hover {{ background:rgba(110,245,238,64); }}
QToolButton#talk[live="true"] {{ background:rgba(110,245,238,90); border-color:{MINT}; }}
QToolButton#muted[on="true"] {{ color:{CORAL}; }}
QPushButton#example {{ background:transparent; border:none; border-bottom:1px solid rgba(255,255,255,16); color:{TEXT}; text-align:left; padding:12px 2px; }}
QPushButton#example:hover {{ color:{MINT}; }}
QPushButton#example:focus {{ outline:none; color:{MINT}; }}
QPushButton#timer {{ background:{SURFACE}; border:1px solid {LINE}; border-radius:12px; padding:3px 10px; color:{TEXT}; }}
QPushButton#timer:hover {{ border-color:{CORAL}; color:{CORAL}; }}
QScrollBar:vertical {{ background:transparent; width:8px; margin:4px 2px; }}
QScrollBar::handle:vertical {{ background:#22302D; border-radius:3px; min-height:30px; }}
QScrollBar::handle:vertical:hover {{ background:{FAINT}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background:none; height:0; }}
QDialog, QTabWidget::pane, QTabWidget > QWidget {{ background:{GROUND}; }}
QTabBar::tab {{ background:transparent; color:{MUTED}; padding:8px 14px; border:none; }}
QTabBar::tab:selected {{ color:{TEXT}; border-bottom:2px solid {TEAL}; }}
QTabWidget::pane {{ border:1px solid {LINE}; border-radius:10px; }}
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background:{SURFACE}; border:1px solid {LINE}; border-radius:8px; padding:6px 9px; color:{TEXT}; }}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color:{TEAL}; }}
QComboBox QAbstractItemView {{ background:{SURFACE}; border:1px solid {LINE}; selection-background-color:{DEEP}; color:{TEXT}; }}
QDialogButtonBox QPushButton, QPushButton#plain {{ background:{SURFACE}; border:1px solid {LINE}; border-radius:8px; padding:7px 16px; color:{TEXT}; }}
QDialogButtonBox QPushButton:default {{ background:{TEAL}; color:{GROUND}; border:none; }}
QCheckBox {{ color:{TEXT}; }}
QMenu {{ background:{SURFACE}; border:1px solid {LINE}; padding:4px; }}
QMenu::item {{ padding:6px 18px; border-radius:6px; }}
QMenu::item:selected {{ background:{SURFACE_2}; }}
"""


def line_icon(kind: str, color: str = MUTED, size: int = 20) -> QIcon:
    """Small hairline icons for the header and input bar."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(2, 2)
    pen = QPen(QColor(color), 1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s_ = size
    if kind == "new":        # a page with a plus
        p.drawRoundedRect(QRectF(s_ * .2, s_ * .18, s_ * .6, s_ * .64), 3, 3)
        p.drawLine(QPointF(s_ * .5, s_ * .38), QPointF(s_ * .5, s_ * .62))
        p.drawLine(QPointF(s_ * .38, s_ * .5), QPointF(s_ * .62, s_ * .5))
    elif kind in ("mic", "mic_off"):
        p.drawRoundedRect(QRectF(s_ * .38, s_ * .14, s_ * .24, s_ * .42), s_ * .12, s_ * .12)
        path = QPainterPath(QPointF(s_ * .26, s_ * .44))
        path.cubicTo(QPointF(s_ * .26, s_ * .72), QPointF(s_ * .74, s_ * .72), QPointF(s_ * .74, s_ * .44))
        p.drawPath(path)
        p.drawLine(QPointF(s_ * .5, s_ * .68), QPointF(s_ * .5, s_ * .84))
        if kind == "mic_off":
            p.drawLine(QPointF(s_ * .2, s_ * .18), QPointF(s_ * .8, s_ * .84))
    elif kind == "settings":  # two sliders
        for y, x in ((.34, .62), (.66, .38)):
            p.drawLine(QPointF(s_ * .18, s_ * y), QPointF(s_ * .82, s_ * y))
            p.setBrush(QColor(GROUND))
            p.drawEllipse(QPointF(s_ * x, s_ * y), s_ * .08, s_ * .08)
            p.setBrush(Qt.NoBrush)
    elif kind == "send":
        path = QPainterPath(QPointF(s_ * .5, s_ * .78))
        path.lineTo(QPointF(s_ * .5, s_ * .24))
        path.moveTo(QPointF(s_ * .3, s_ * .44))
        path.lineTo(QPointF(s_ * .5, s_ * .24))
        path.lineTo(QPointF(s_ * .7, s_ * .44))
        p.drawPath(path)
    elif kind == "stop":
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(s_ * .32, s_ * .32, s_ * .36, s_ * .36), 2, 2)
    p.end()
    return QIcon(pm)


def make_icon(color=TEAL) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(GROUND))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, 64, 64, 16, 16)
    pen = QPen(QColor(color), 5)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    path = QPainterPath()
    path.moveTo(10, 32)
    for i, x in enumerate(range(14, 56, 6)):
        path.lineTo(x, 32 + (-13 if i % 2 else 13) * math.sin(math.pi * (x - 10) / 44))
    path.lineTo(54, 32)
    p.drawPath(path)
    p.end()
    return QIcon(pm)
