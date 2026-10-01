"""Palette, stylesheet and font scaling (spec §7.4)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

COLORS = {
    "charging": "#2ea043",
    "discharging": "#f0883e",
    "idle": "#8b949e",
    "offline": "#8b949e",
    "red": "#e5534b",
    "orange": "#f0883e",
    "blue": "#1f6feb",
}
_base_point_size: float | None = None


def is_dark(theme: str) -> bool:
    if theme == "dark":
        return True
    if theme == "light":
        return False
    app = QApplication.instance()
    return app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark


def palette(dark: bool) -> QPalette:
    if dark:
        window, base, text, button, mid = "#202124", "#2b2c2f", "#e8eaed", "#303134", "#5f6368"
    else:
        window, base, text, button, mid = "#f7f7f8", "#ffffff", "#1b1b1b", "#eeeeee", "#9aa0a6"
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: window, QPalette.ColorRole.Base: base,
        QPalette.ColorRole.AlternateBase: button, QPalette.ColorRole.Button: button,
        QPalette.ColorRole.WindowText: text, QPalette.ColorRole.Text: text,
        QPalette.ColorRole.ButtonText: text, QPalette.ColorRole.ToolTipBase: base,
        QPalette.ColorRole.ToolTipText: text, QPalette.ColorRole.PlaceholderText: mid,
        QPalette.ColorRole.Mid: mid, QPalette.ColorRole.Highlight: COLORS["blue"],
        QPalette.ColorRole.HighlightedText: "#ffffff",
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(mid))
    return p


def stylesheet(dark: bool) -> str:
    muted = "#9aa0a6" if dark else "#5f6368"
    red_bg, red_fg = ("#5c1d1d", "#ffd7d5") if dark else ("#fde2e1", "#8b1a14")
    orange_bg, orange_fg = ("#4d3316", "#ffe2c7") if dark else ("#fff0dd", "#7a3d00")
    return f"""
QFrame[role="card"] {{ background: rgba(128, 128, 128, 0.14); border-radius: 8px; }}
QLabel[role="muted"], QLabel[role="card-title"] {{ color: {muted}; }}
QLabel[role="banner-red"] {{ background: {red_bg}; color: {red_fg}; border: 1px solid #e5534b;
    border-radius: 8px; padding: 8px 12px; font-weight: 600; }}
QLabel[role="banner-orange"] {{ background: {orange_bg}; color: {orange_fg}; border: 1px solid #f0883e;
    border-radius: 8px; padding: 8px 12px; font-weight: 600; }}
QLabel[role="badge-critical"] {{ background: {red_bg}; color: {red_fg}; border-radius: 8px; padding: 0 6px; }}
QLabel[role="badge-warn"] {{ background: {orange_bg}; color: {orange_fg}; border-radius: 8px; padding: 0 6px; }}
QPushButton[role="seg"] {{ border: none; border-radius: 12px; padding: 4px 12px;
    background: rgba(128, 128, 128, 0.18); }}
QPushButton[role="seg"]:checked {{ background: #1f6feb; color: white; }}
"""


def apply(app: QApplication, theme: str, font_scale: float) -> None:
    global _base_point_size
    if _base_point_size is None:
        size = app.font().pointSizeF()
        _base_point_size = size if size > 0 else 9.0
    dark = is_dark(theme)
    app.setStyle("Fusion")
    app.setPalette(palette(dark))
    font = app.font()
    font.setPointSizeF(_base_point_size * font_scale)
    app.setFont(font)
    app.setStyleSheet(stylesheet(dark))


def base_point_size() -> float:
    return _base_point_size or 9.0
