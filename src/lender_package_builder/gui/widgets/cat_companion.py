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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..theme import GRADIENT_PINK, GRADIENT_PURPLE

# A 22x22 grid of named colors (None = transparent), built and mirrored
# left-to-right around column 10/11 -- see _build_base_grid(). Scaled
# up with a FAST/nearest-neighbor transform, never smooth, which is
# what keeps every square crisp ("pixelated") rather than blurred.
_GRID_W, _GRID_H = 22, 22
_HALF = 11  # columns 0..10, mirrored to column (21 - col)
_SCALE = 7  # on-screen size: 154x154

_F = "#A68B70"  # fur
_D = "#6E5B48"  # dark fur / stripes / tail / shading
_P = GRADIENT_PINK  # inner ear, nose, collar
_EYE = "#E8B04B"  # eye base -- bright enough to read against the fur, unlike the old single dark dot
_PUPIL = "#2A1F2E"
_W = "#F5F0E6"  # paw-tip highlight
_SPARKLE = GRADIENT_PURPLE

_SLEEP_FRAME_MS = 900
_WAKE_MS = 400
_STRETCH_FRAME_MS = 450
_DANCE_FRAME_MS = 220
_DANCE_LOOPS = 3
_SLEEP_CYCLE_FRAMES = 4  # breathe, small z, medium z, big z -- then a beat with none

# (pose, frame_count, frame_duration_ms, next_pose_or_None)
_SEQUENCE_AFTER_WAKE = [
    ("wake", 1, _WAKE_MS),
    ("stretch", 2, _STRETCH_FRAME_MS),
    ("dance", 4, _DANCE_FRAME_MS),
]


def _new_grid() -> list[list[str | None]]:
    return [[None] * _GRID_W for _ in range(_GRID_H)]


def _set(grid, row: int, col: int, color: str) -> None:
    grid[row][col] = color
    grid[row][_GRID_W - 1 - col] = color


def _fill(grid, row: int, left_start: int, color: str = _F, right_edge: int = _HALF - 1) -> None:
    for x in range(left_start, right_edge + 1):
        grid[row][x] = color
        grid[row][_GRID_W - 1 - x] = color


def _build_base_grid(eyes_closed: bool) -> list[list[str | None]]:
    """The sitting cat silhouette shared by every pose -- ears, a head
    narrower than the body (the width step between them, plus a
    pinched-in "neck" row, is what reads as a head rather than one
    blob), a small pink collar, a body, front paws, and a dark tail
    that stays visually distinct from the body it curls against
    (same color as the body would make it disappear on contact) --
    with only the eyes varying here (closed for sleep, open for
    everything else; wake/stretch/dance widen them further on top).
    """

    grid = _new_grid()

    # ears, centered above the head rather than out at its old full
    # width, with a pink inner-ear patch
    _set(grid, 0, 7, _F)
    for c in (6, 7, 8):
        _set(grid, 1, c, _F)
    for c in (5, 6, 7, 8):
        _set(grid, 2, c, _F)
    _set(grid, 2, 6, _P)
    for c in (5, 6, 7, 8, 9):
        _set(grid, 3, c, _F)
    _set(grid, 3, 6, _P)

    # head -- narrows toward the top (near the ears), widens slightly
    # at the cheeks, then pinches in again at row 10 (the neck) before
    # the body flares out wider below
    for row, start in {4: 6, 5: 4, 6: 3, 7: 3, 8: 3, 9: 4, 10: 5}.items():
        _fill(grid, row, start)

    # eyes: two rows tall, a bright base with a dark pupil -- far more
    # legible at this scale than the old single dim pixel
    if eyes_closed:
        _set(grid, 7, 4, _D)
        _set(grid, 7, 5, _D)
    else:
        for row in (6, 7):
            _set(grid, row, 4, _EYE)
            _set(grid, row, 5, _EYE)
        _set(grid, 7, 5, _PUPIL)

    # whisker, just outside the head's edge at the cheek row so it
    # reads as emanating from the face instead of floating in space
    _set(grid, 8, 2, _D)

    # nose: a small triangle, wider at the top and pointed at the
    # bottom (toward the mouth), rather than a single flat dot
    _set(grid, 8, 9, _P)
    _set(grid, 8, 10, _P)
    _set(grid, 9, 10, _P)

    # mouth: two small dots just under the nose's point -- a minimal
    # ":3"-style kitty smile, not a second collar-like band
    _set(grid, 10, 9, _D)

    # a couple of tabby forehead stripes
    _set(grid, 5, 6, _D)
    _set(grid, 4, 7, _D)

    # body -- narrower than before (a slimmer build reads cuter), right
    # side still stops short so the tail can show
    for row in range(11, 19):
        for x in range(2, _HALF):
            grid[row][x] = _F
        for x in range(_HALF, _GRID_W - 4):
            grid[row][x] = _F

    # a thin collar band across the top of the body (the neck line),
    # with a small tag below it -- kept off the face itself so it
    # can't be mistaken for a mouth
    _fill(grid, 11, 5, _P)
    _set(grid, 12, 10, _EYE)  # collar tag, just below the band

    for row, col in [(12, 3), (12, 7), (14, 2), (16, 5)]:
        _set(grid, row, col, _D)

    # front paws, with a gap between them -- inset to match the
    # slimmer body above them
    for row in range(19, 21):
        _fill(grid, row, 4, right_edge=_HALF - 2)
    for c in range(4, _HALF - 1):
        grid[21][c] = _W
        grid[21][_GRID_W - 1 - c] = _W

    # tail, curling in the gap left open on the body's right side --
    # dark rather than fur-colored so it stays visible where it meets
    # the body's edge
    for (row, col), color in {
        (10, 19): _D, (11, 20): _D, (12, 21): _D, (13, 21): _D,
        (14, 21): _D, (15, 21): _D, (16, 20): _D, (17, 19): _D,
    }.items():
        grid[row][col] = color

    return grid


def _widen_eyes(grid) -> None:
    """A bright highlight pixel added to each pupil -- used for
    wake/stretch/dance, layered on top of the shared base grid's
    already-open eyes to give a wide-eyed "just woke up" sparkle.
    """

    _set(grid, 6, 5, _W)


def _raised_arm(grid, side: str) -> None:
    """A paw raised straight up from the shoulder -- "left"/"right" as
    seen on screen (mirrored automatically for the opposite side isn't
    applicable here since this is explicitly one-sided, unlike the
    symmetric body/head helpers above).
    """

    col = 1 if side == "left" else _GRID_W - 2
    for row in (7, 8, 9, 10):
        grid[row][col] = _F
    grid[6][col] = _D


def _sparkle(grid, row: int, col: int) -> None:
    grid[row][col] = _SPARKLE


def _draw_grid(painter: QPainter, grid, y_offset: int = 0) -> None:
    # QColor objects are built once per distinct hex string and reused
    # -- constructing a fresh QColor for every filled cell (100+ per
    # frame) triggered a real native refcount crash in this
    # environment's PySide6 build; caching sidesteps it and is cheaper
    # regardless.
    color_cache: dict[str, QColor] = {}
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(Qt.PenStyle.NoPen)
    for y, row in enumerate(grid):
        for x, color in enumerate(row):
            if color is None:
                continue
            qcolor = color_cache.get(color)
            if qcolor is None:
                qcolor = QColor(color)
                color_cache[color] = qcolor
            painter.setBrush(qcolor)
            painter.drawRect(x, y + y_offset, 1, 1)


def _draw_cat(painter: QPainter, pose: str, frame: int) -> None:
    if pose == "sleep":
        grid = _build_base_grid(eyes_closed=True)
        y_offset = -1 if frame % 2 else 0
        # a little "z" that climbs up and to the right over the 4-frame
        # sleep cycle (small and low -> medium -> big and high), then
        # disappears for a beat before starting over -- a single static
        # mark, even a bold one, didn't read as "sleeping" so much as
        # just "there's a mark here"; the rise is what sells it
        if frame == 1:
            grid[3][16] = _PUPIL
            grid[3][17] = _PUPIL
        elif frame == 2:
            grid[2][18] = _PUPIL
            grid[2][19] = _PUPIL
            grid[1][17] = _PUPIL
            grid[1][18] = _PUPIL
        elif frame == 3:
            for col in (18, 19, 20, 21):
                grid[0][col] = _PUPIL
            grid[1][20] = _PUPIL
            grid[1][21] = _PUPIL
        _draw_grid(painter, grid, y_offset)
    elif pose == "wake":
        grid = _build_base_grid(eyes_closed=False)
        _widen_eyes(grid)
        _draw_grid(painter, grid)
    elif pose == "stretch":
        grid = _build_base_grid(eyes_closed=frame == 0)
        if frame == 1:
            _widen_eyes(grid)
        _raised_arm(grid, "left")
        _raised_arm(grid, "right")
        _draw_grid(painter, grid)
    elif pose == "dance":
        grid = _build_base_grid(eyes_closed=False)
        _widen_eyes(grid)
        left_up = frame % 4 in (0, 1)
        right_up = frame % 4 in (2, 3)
        if left_up:
            _raised_arm(grid, "left")
        if right_up:
            _raised_arm(grid, "right")
        if frame % 2 == 0:
            _sparkle(grid, 0, 0 if left_up else _GRID_W - 1)
        lift = 1 if frame % 2 else 0
        _draw_grid(painter, grid, -lift)


def _render_frame(pose: str, frame: int) -> QPixmap:
    image = QImage(_GRID_W, _GRID_H, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    _draw_cat(painter, pose, frame)
    painter.end()
    pixmap = QPixmap.fromImage(image)
    return pixmap.scaled(
        _GRID_W * _SCALE,
        _GRID_H * _SCALE,
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
        self.setFixedSize(_GRID_W * _SCALE, _GRID_H * _SCALE)

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

        self._frame = (self._frame + 1) % _SLEEP_CYCLE_FRAMES
        self._render()

    def _render(self) -> None:
        frame_in_pose = self._frame % 4 if self._pose in ("sleep", "dance") else self._frame % 2
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
