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

# A 22x24 grid of named colors (None = transparent), built and mirrored
# left-to-right around column 10/11 -- see _build_base_grid(). Scaled
# up with a FAST/nearest-neighbor transform, never smooth, which is
# what keeps every square crisp ("pixelated") rather than blurred.
#
# One continuous round silhouette (no separate narrow-head/wide-body
# break, unlike earlier versions) plus a ground mound underneath --
# modeled on a reference image of a round, chubby, asymmetrically
# marked pixel-art cat sitting on a dirt patch with one paw raised.
_GRID_W, _GRID_H = 22, 24
_HALF = 11  # columns 0..10, mirrored to column (21 - col)
_SCALE = 7  # on-screen size: 154x168

_F = "#A68B70"  # fur
_D = "#6E5B48"  # dark fur -- the asymmetric ear/side patch, tail tip
_P = GRADIENT_PINK  # inner ear, nose
_PUPIL = "#2A1F2E"
_W = "#F5F0E6"  # paw-tip highlight
_GROUND = "#8C6239"  # the mound the cat sits on
_SPARKLE = GRADIENT_PURPLE

# half-width profile (row -> leftmost filled column) for the round
# body -- rows with start <= 1 are wide enough to reach the tail's
# reserved gap on the right and need the asymmetric fill below instead
# of the normal mirrored one
_BODY_WIDTHS = {
    3: 7, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1, 9: 0, 10: 0, 11: 0,
    12: 0, 13: 0, 14: 1, 15: 2, 16: 3, 17: 5, 18: 7,
}

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


def _fill_with_tail_gap(grid, row: int, left_start: int, color: str = _F) -> None:
    # Like _fill, but for rows wide enough that a plain mirror would
    # reach into the tail's reserved gap on the right -- fills the
    # right side only up to _GRID_W - 3, same as the manual body loop
    # below used to.
    for x in range(left_start, _HALF):
        grid[row][x] = color
    for x in range(_HALF, _GRID_W - 2):
        grid[row][x] = color


def _build_base_grid(eyes_closed: bool) -> list[list[str | None]]:
    """The round, chubby cat silhouette shared by every pose: small
    ears, one continuous round body (head and body are the same shape,
    not a narrower head atop a wider body), an asymmetric dark patch
    over the left ear and down the left side (a one-sided marking,
    like the reference image's black-ear/black-back cat, just in the
    tabby dark tone), two front feet, a short dark-tipped tail, and a
    ground mound underneath -- with only the eyes varying here (closed
    for sleep, open for everything else; wake/dance widen them further
    on top). The raised paw is NOT part of this shared silhouette --
    see `_raised_arm()` -- since sleep shows both paws tucked down.
    """

    grid = _new_grid()

    # ears: small, close together, with a pink inner-ear patch
    _set(grid, 0, 6, _F)
    _fill(grid, 1, 5, right_edge=7)
    _fill(grid, 2, 5, right_edge=8)
    _set(grid, 1, 6, _P)

    # one continuous round silhouette -- see _BODY_WIDTHS's own comment
    for row, start in _BODY_WIDTHS.items():
        if start <= 1:
            _fill_with_tail_gap(grid, row, start)
        else:
            _fill(grid, row, start)

    # eyes: plain and simple, a closed line for sleep or a small dark
    # oval when open (no separate bright base -- the reference's eyes
    # are minimal, not a lit-up amber)
    if eyes_closed:
        _set(grid, 7, 7, _PUPIL)
        _set(grid, 7, 8, _PUPIL)
    else:
        for row in (6, 7):
            _set(grid, row, 7, _PUPIL)
            _set(grid, row, 8, _PUPIL)

    # nose: a small triangle, wider at the top and pointed at the
    # bottom (toward the mouth)
    _set(grid, 8, 9, _P)
    _set(grid, 8, 10, _P)
    _set(grid, 9, 10, _P)

    # mouth: two small dots just under the nose's point -- a minimal
    # ":3"-style kitty smile
    _set(grid, 10, 9, _D)

    # the asymmetric dark patch -- direct (one-sided) assignment, not
    # the mirroring _set, since the whole point is the right side
    # stays plain fur
    grid[0][6] = _D
    for c in (5, 6, 7):
        grid[1][c] = _D
    for c in (5, 6, 7, 8):
        grid[2][c] = _D
    for row, cols in {3: (7, 8), 4: (5, 6), 5: (4, 5), 6: (3, 4), 7: (2, 3), 8: (1, 2)}.items():
        for c in cols:
            grid[row][c] = _D

    # feet: two small nubs peeking out from under the round body
    _fill(grid, 19, 6, right_edge=_HALF - 3)
    for c in range(6, _HALF - 3):
        grid[20][c] = _W
        grid[20][_GRID_W - 1 - c] = _W

    # tail: a short stub with a dark tip, peeking out on the right
    for (row, col), color in {
        (13, 19): _F, (14, 20): _F, (14, 19): _D, (15, 20): _D,
    }.items():
        grid[row][col] = color

    # the ground mound the cat sits on
    for row, inset in {21: 3, 22: 1, 23: 0}.items():
        for x in range(inset, _GRID_W - inset):
            grid[row][x] = _GROUND

    return grid


def _widen_eyes(grid) -> None:
    """A bright highlight pixel added to one eye -- used for
    wake/stretch/dance, layered on top of the shared base grid's
    already-open eyes to give a wide-eyed "just woke up" sparkle.
    """

    grid[6][7] = _W


def _raised_arm(grid, side: str) -> None:
    """A paw raised up alongside the head, ending in a slightly
    rounded tip rather than a single-pixel-wide stick -- "left"/"right"
    as seen on screen. Not part of the shared base grid: sleep shows
    both paws tucked down, so this is layered on only for wake/
    stretch/dance.
    """

    near, far = (1, 2) if side == "left" else (_GRID_W - 2, _GRID_W - 3)
    grid[2][near] = _F
    for row in (3, 4, 5):
        grid[row][near] = _F
        grid[row][far] = _F
    grid[6][near] = _F


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
        _raised_arm(grid, "right")
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
