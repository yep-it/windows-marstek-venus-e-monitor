"""Small building blocks shared by the windows."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QVBoxLayout, QWidget,
)


def scaled_font(factor: float, bold: bool = False) -> QFont:
    font = QFont(QApplication.font())
    size = font.pointSizeF() if font.pointSizeF() > 0 else 9.0
    font.setPointSizeF(max(6.0, size * factor))
    font.setBold(bold)
    return font


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def label(text: str = "", role: str | None = None, factor: float = 1.0, bold: bool = False,
          wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    if factor != 1.0 or bold:
        widget.setFont(scaled_font(factor, bold))
    widget.setWordWrap(wrap)
    return widget


class Card(QFrame):
    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        self.title = label(title.upper(), "card-title", 0.8)
        self.value = label("—", None, 1.3, True, wrap=True)
        self.sub = label("", "muted", 0.85, wrap=True)
        self.sub.hide()
        for widget in (self.title, self.value, self.sub):
            layout.addWidget(widget)

    def set(self, value: str, sub: str = "") -> None:
        self.value.setText(value)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))

    def set_accent(self, color: str | None) -> None:
        self.setStyleSheet(f'QFrame[role="card"] {{ border-left: 4px solid {color}; }}' if color else "")


class Segmented(QWidget):
    """A row of exclusive pill buttons."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._keys: list[str] = []
        for i, (key, text) in enumerate(options):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty("role", "seg")
            button.setChecked(i == 0)
            self.group.addButton(button, i)
            layout.addWidget(button)
            self._keys.append(key)
        layout.addStretch(1)
        self.group.idClicked.connect(lambda i: self.changed.emit(self._keys[i]))

    def value(self) -> str:
        return self._keys[self.group.checkedId()]

    def set_value(self, key: str) -> None:
        self.group.button(self._keys.index(key)).setChecked(True)
