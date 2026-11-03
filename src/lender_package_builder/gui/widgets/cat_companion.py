"""A small pixel-art cat that sits in the corner of the screen while a
build runs, sleeping -- then wakes up, stretches, and does a little
celebration dance when the build finishes.

Real user request: "add a little pop up notification for when its
done. the pop up should be a pixelated cat or smth"; refined to "the
continuous sleeping kitty in the corner or the screen then when its
done it wakes up stretches and does a lil dance."

Drawn procedurally (no image assets) onto a small internal canvas with
antialiasing off, then scaled up with a FAST (nearest-neighbor, never
smooth) transform -- that low-resolution-then-upscale combination is
what produces the blocky "pixelated" look, rather than hand-placing
individual pixels one at a time.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap, QPolygon
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..theme import GRADIENT_PINK, GRADIENT_PURPLE, SIDEBAR_TEXT

_CANVAS_W, _CANVAS_H = 32, 24
_SCALE = 5  # on-screen size: 160x120

_FUR = QColor("#A68B70")
_FUR_DARK = QColor("#6E5B48")
_BELLY = QColor("#E9DFCF")
_NOSE = QColor(GRADIENT_PINK)
_BLUSH = QColor("#E8A6A0")
_INK = QColor(SIDEBAR_TEXT)
_SPARKLE = QColor(GRADIENT_PURPLE)

_SLEEP_FRAME_MS = 900
_WAKE_MS = 400
_STRETCH_FRAME_MS = 450
_DANCE_FRAME_MS = 220
_DANCE_LOOPS = 3

# (pose, frame_count, frame_duration_ms, next_pose_or_None)
_SEQUENCE_AFTER_WAKE = [
    ("wake", 1, _WAKE_MS),
    ("stretch", 2, _STRETCH_FRAME_MS),
    ("dance", 4, _DANCE_FRAME_MS),
]


def _draw_cat(painter: QPainter, pose: str, frame: int) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(Qt.PenStyle.NoPen)
    if pose == "sleep":
        _draw_sleeping(painter, frame)
    elif pose == "wake":
        _draw_waking(painter)
    elif pose == "stretch":
        _draw_stretching(painter, frame)
    elif pose == "dance":
        _draw_dancing(painter, frame)


def _ears(painter: QPainter, cx: int, base_y: int, tip_y: int, spread: int) -> None:
    painter.setBrush(_FUR)
    painter.drawPolygon(QPolygon([QPoint(cx - spread, base_y), QPoint(cx - spread + 2, tip_y), QPoint(cx - spread + 4, base_y)]))
    painter.drawPolygon(QPolygon([QPoint(cx + spread - 4, base_y), QPoint(cx + spread - 2, tip_y), QPoint(cx + spread, base_y)]))
    painter.setBrush(_NOSE)
    painter.drawPolygon(QPolygon([QPoint(cx - spread + 1, base_y - 1), QPoint(cx - spread + 2, tip_y + 1), QPoint(cx - spread + 3, base_y - 1)]))
    painter.drawPolygon(QPolygon([QPoint(cx + spread - 3, base_y - 1), QPoint(cx + spread - 2, tip_y + 1), QPoint(cx + spread - 1, base_y - 1)]))


def _tabby_stripes(painter: QPainter, cx: int, top_y: int) -> None:
    """A few short forehead/back stripes -- the one detail that reads
    as "tabby" rather than just a plain brown cat.
    """

    painter.setBrush(_FUR_DARK)
    painter.drawRect(cx - 1, top_y, 2, 2)
    painter.drawRect(cx - 5, top_y + 1, 2, 2)
    painter.drawRect(cx + 3, top_y + 1, 2, 2)


def _blush(painter: QPainter, left_x: int, right_x: int, y: int) -> None:
    painter.setBrush(_BLUSH)
    painter.drawRect(left_x, y, 2, 1)
    painter.drawRect(right_x, y, 2, 1)


def _draw_sleeping(painter: QPainter, frame: int) -> None:
    bob = 1 if frame % 2 else 0
    painter.setBrush(_FUR_DARK)
    painter.drawEllipse(QRect(2, 15 - bob, 8, 6))  # curled tail
    painter.setBrush(_FUR)
    painter.drawEllipse(QRect(7, 11 - bob, 20, 11))  # loaf body
    _ears(painter, 16, 10 - bob, 6 - bob, 7)
    _tabby_stripes(painter, 16, 9 - bob)
    _blush(painter, 10, 20, 16 - bob)
    painter.setBrush(_INK)
    painter.drawRect(11, 14 - bob, 4, 1)  # closed eyes, a soft curved line
    painter.drawRect(17, 14 - bob, 4, 1)
    painter.setBrush(_NOSE)
    painter.drawRect(15, 16 - bob, 2, 1)
    if frame % 2:
        painter.setBrush(_INK)
        painter.drawRect(25, 4, 2, 2)
        painter.drawRect(28, 1, 2, 2)


def _draw_waking(painter: QPainter) -> None:
    painter.setBrush(_FUR_DARK)
    painter.drawEllipse(QRect(2, 15, 8, 6))
    painter.setBrush(_FUR)
    painter.drawEllipse(QRect(7, 11, 20, 11))
    _ears(painter, 16, 9, 3, 7)
    _tabby_stripes(painter, 16, 8)
    _blush(painter, 9, 20, 15)
    painter.setBrush(_INK)
    painter.drawEllipse(QRect(11, 12, 4, 4))  # big round eyes, just opened
    painter.drawEllipse(QRect(17, 12, 4, 4))
    painter.setBrush(_NOSE)
    painter.drawRect(15, 17, 2, 1)


def _draw_stretching(painter: QPainter, frame: int) -> None:
    reach = frame  # 0 -> starting to lean in, 1 -> full stretch
    painter.setBrush(_FUR_DARK)
    painter.drawRect(26 - reach * 2, 16, 4, 2)  # tail up, slightly forward
    painter.setBrush(_FUR)
    # arched back body, higher at the rear
    painter.drawEllipse(QRect(9, 9 - reach, 17, 10))
    # front legs stretched forward along the ground, paw tips a shade darker
    leg_x = 4 - reach * 3
    leg_w = 9 + reach * 3
    painter.drawRect(leg_x, 18, leg_w, 3)
    painter.setBrush(_FUR_DARK)
    painter.drawRect(leg_x, 18, 3, 3)
    _ears(painter, 14, 8 - reach, 4 - reach, 6)
    _tabby_stripes(painter, 14, 7 - reach)
    _blush(painter, 8, 17, 14 - reach)
    painter.setBrush(_INK)
    painter.drawEllipse(QRect(9, 10 - reach, 4, 4))
    painter.drawEllipse(QRect(15, 10 - reach, 4, 4))
    painter.setBrush(_NOSE)
    painter.drawRect(13, 15 - reach, 2, 1)


def _draw_dancing(painter: QPainter, frame: int) -> None:
    tilt = [-2, 0, 2, 0][frame % 4]
    lift = [0, 1, 0, 1][frame % 4]
    cx = 16 + tilt // 2
    painter.setBrush(_FUR_DARK)
    painter.drawRect(cx + 7, 17 - lift, 3, 5)  # tail swishing
    painter.setBrush(_FUR)
    painter.drawEllipse(QRect(cx - 8, 10 - lift, 16, 10))  # upright body
    painter.drawRect(cx - 7, 18 - lift, 5, 3)  # left foot
    painter.drawRect(cx + 2, 18 - lift, 5, 3)  # right foot
    # paws up, alternating sides
    left_up = frame % 4 in (0, 1)
    right_up = frame % 4 in (2, 3)
    painter.drawRect(cx - 10, (6 if left_up else 12) - lift, 3, 5)
    painter.drawRect(cx + 7, (6 if right_up else 12) - lift, 3, 5)
    _ears(painter, cx, 8 - lift, 4 - lift, 6)
    _tabby_stripes(painter, cx, 7 - lift)
    _blush(painter, cx - 6, cx + 4, 13 - lift)
    painter.setBrush(_INK)
    painter.drawEllipse(QRect(cx - 5, 11 - lift, 4, 4))
    painter.drawEllipse(QRect(cx + 1, 11 - lift, 4, 4))
    painter.setBrush(_NOSE)
    painter.drawRect(cx - 1, 16 - lift, 2, 1)
    if frame % 2 == 0:
        painter.setBrush(_SPARKLE)
        painter.drawRect(cx - 13, 4 - lift, 2, 2)
        painter.drawRect(cx + 12, 8 - lift, 2, 2)


def _render_frame(pose: str, frame: int) -> QPixmap:
    image = QImage(_CANVAS_W, _CANVAS_H, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    _draw_cat(painter, pose, frame)
    painter.end()
    pixmap = QPixmap.fromImage(image)
    return pixmap.scaled(
        _CANVAS_W * _SCALE,
        _CANVAS_H * _SCALE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


class CatCompanionWidget(QWidget):
    """Frameless, always-on-top, click-to-focus-parent companion. Call
    `start_sleeping()` once (e.g. when the first build starts) and
    `wake_and_celebrate()` each time a build finishes successfully --
    it returns to sleep on its own once the little dance is done.
    """

    def __init__(self, parent_window: QWidget | None = None):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._parent_window = parent_window
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(_CANVAS_W * _SCALE, _CANVAS_H * _SCALE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel()
        self._label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout.addWidget(self._label)

        self._pose = "sleep"
        self._frame = 0
        self._queue: list[tuple[str, int, int]] = []

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

    # -- public API ----------------------------------------------

    def start_sleeping(self) -> None:
        self._place_in_corner()
        self._pose = "sleep"
        self._frame = 0
        self._queue = []
        self._render()
        self.show()
        self._timer.start(_SLEEP_FRAME_MS)

    def wake_and_celebrate(self) -> None:
        if not self.isVisible():
            self.start_sleeping()
        self._queue = list(_SEQUENCE_AFTER_WAKE)
        self._advance()

    # -- internals ----------------------------------------------

    def _place_in_corner(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        margin = 18
        self.move(geo.right() - self.width() - margin, geo.bottom() - self.height() - margin)

    def _advance(self) -> None:
        if self._queue:
            pose, frame_count, interval = self._queue[0]
            if pose != self._pose:
                self._pose = pose
                self._frame = 0
            else:
                self._frame += 1
            if self._frame >= frame_count * (_DANCE_LOOPS if pose == "dance" else 1):
                self._queue.pop(0)
                if not self._queue:
                    self._pose = "sleep"
                    self._frame = 0
                    self._render()
                    self._timer.start(_SLEEP_FRAME_MS)
                    return
                pose, frame_count, interval = self._queue[0]
                self._pose = pose
                self._frame = 0
            self._render()
            self._timer.start(interval)
            return

        self._frame = (self._frame + 1) % 2
        self._render()

    def _render(self) -> None:
        frame_in_pose = self._frame % 2 if self._pose != "dance" else self._frame % 4
        if self._pose == "stretch":
            frame_in_pose = min(self._frame, 1)
        self._label.setPixmap(_render_frame(self._pose, frame_in_pose))

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._parent_window is not None:
            self._parent_window.show()
            self._parent_window.raise_()
            self._parent_window.activateWindow()
        super().mousePressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        # A separate top-level, always-on-top widget with its own
        # running QTimer -- closing it must stop that timer, not just
        # hide the window, or the animation loop keeps firing
        # indefinitely against a widget nothing else references.
        self._timer.stop()
        super().closeEvent(event)
