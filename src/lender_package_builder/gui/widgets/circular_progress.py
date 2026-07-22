"""A small circular percentage indicator, purely a visual companion to
the real progress data (`ProgressView.progress_bar`, a normal
`QProgressBar`, stays the source of truth other code/tests read from).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..theme import ACCENT, ACCENT_DISABLED, CARD_BORDER, TEXT_PRIMARY

_DIAMETER = 96
_RING_WIDTH = 8


class CircularProgressIndicator(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._percent = 0
        self._indeterminate = True
        self.setFixedSize(_DIAMETER, _DIAMETER)

    def set_value(self, percent: int) -> None:
        self._indeterminate = False
        self._percent = max(0, min(100, percent))
        self.update()

    def set_indeterminate(self) -> None:
        self._indeterminate = True
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(_RING_WIDTH / 2, _RING_WIDTH / 2, self.width() - _RING_WIDTH, self.height() - _RING_WIDTH)

        track_pen = QPen(QColor(CARD_BORDER))
        track_pen.setWidth(_RING_WIDTH)
        painter.setPen(track_pen)
        painter.drawArc(rect, 0, 360 * 16)

        if self._indeterminate:
            arc_pen = QPen(QColor(ACCENT_DISABLED))
            arc_pen.setWidth(_RING_WIDTH)
            arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arc_pen)
            painter.drawArc(rect, 90 * 16, -90 * 16)
            text = "…"
        else:
            arc_pen = QPen(QColor(ACCENT))
            arc_pen.setWidth(_RING_WIDTH)
            arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arc_pen)
            span = round(360 * 16 * (self._percent / 100))
            if span:
                painter.drawArc(rect, 90 * 16, -span)
            text = f"{self._percent}%"

        painter.setPen(QColor(TEXT_PRIMARY))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(12)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
