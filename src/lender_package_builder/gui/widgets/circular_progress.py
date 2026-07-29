"""A small circular percentage indicator, purely a visual companion to
the real progress data (`ProgressView.progress_bar`, a normal
`QProgressBar`, stays the source of truth other code/tests read from).

The indeterminate state (used whenever a stage hasn't reported a real
total yet) spins continuously via `_spin_timer` -- a real user complaint
was that a static indicator gave no visual sign the app was still
working versus having silently frozen, especially during the long
content-analysis/comparison stages. The spin animation is purely
decorative (never read by tests/other code, unlike `_percent`), so it
carries no risk to the real progress-tracking contract.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..theme import ACCENT, ACCENT_DISABLED, CARD_BORDER, TEXT_PRIMARY

_DIAMETER = 96
_RING_WIDTH = 8
_SPIN_INTERVAL_MS = 40
_SPIN_DEGREES_PER_TICK = 6
_SPIN_ARC_SPAN_DEGREES = 90


class CircularProgressIndicator(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._percent = 0
        self._indeterminate = True
        self._spin_angle = 0
        self.setFixedSize(_DIAMETER, _DIAMETER)

        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(_SPIN_INTERVAL_MS)
        self._spin_timer.timeout.connect(self._advance_spin)
        self._spin_timer.start()

    def _advance_spin(self) -> None:
        if not self._indeterminate or not self.isVisible():
            return
        self._spin_angle = (self._spin_angle + _SPIN_DEGREES_PER_TICK) % 360
        self.update()

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
            start_angle = (90 - self._spin_angle) * 16
            painter.drawArc(rect, start_angle, -_SPIN_ARC_SPAN_DEGREES * 16)
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
