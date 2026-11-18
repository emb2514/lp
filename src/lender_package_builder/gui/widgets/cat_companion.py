"""A small pixel-art cat that sits in the corner of the screen while a
build runs, sleeping -- then wakes up, stretches, and does a little
celebration dance when the build finishes.

Real user request: "add a little pop up notification for when its
done. the pop up should be a pixelated cat or smth"; refined to "the
continuous sleeping kitty in the corner or the screen then when its
done it wakes up stretches and does a lil dance," then redrawn against
a reference image of a round, chubby, asymmetrically-marked pixel-art
cat sitting on a dirt mound with its tail raised.

Drawn procedurally (no image assets) onto a small internal canvas with
antialiasing off, then scaled up with a FAST (nearest-neighbor, never
smooth) transform -- that low-resolution-then-upscale combination is
what produces the blocky "pixelated" look, rather than hand-placing
individual pixels one at a time.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..theme import GRADIENT_PINK, GRADIENT_PURPLE

# A grid of named colors (None = transparent) -- see _build_base_grid().
# Scaled up with a FAST/nearest-neighbor transform, never smooth, which
# is what keeps every square crisp ("pixelated") rather than blurred.
#
# One continuous round silhouette (head and body are the same shape,
# no separate narrower-head/wider-body break), an asymmetric dark
# patch over one ear/side flowing into the tail, a ground mound, and a
# thin dark OUTLINE automatically added around every filled shape --
# modeled on a reference image of a round pixel-art cat. The outline
# turned out to matter more than any single shape: without it, every
# part (ears, legs, the tail against the body) blurs into the next and
# the whole thing reads as a formless blob instead of a crisp sprite.
_GRID_W = 25
_HALF = 12  # columns 0..11, mirrored to column (_GRID_W - 1 - col)
_TAIL_GAP = 3  # columns reserved on the right for the raised tail
_TOP_CLEARANCE = 3  # blank rows above the ears so the raised tail can clear head height
_SCALE = 7

_F = "#A68B70"  # fur
_D = "#6E5B48"  # dark fur -- the asymmetric ear/side/tail patch
_P = GRADIENT_PINK  # inner ear, nose
_PUPIL = "#2A1F2E"
_HIGHLIGHT = "#F5F0E6"  # eye-sparkle highlight
_GROUND = "#8C6239"  # the mound the cat sits on
_OUTLINE = "#241A14"
_SPARKLE = GRADIENT_PURPLE

# half-width profile (row -> leftmost filled column, relative to
# _TOP_CLEARANCE) for the round body -- rows with start <= 1 are wide
# enough to reach the tail's reserved gap and need the asymmetric fill
# below instead of the normal mirrored one
_BODY_WIDTHS = {
    3: 8, 4: 6, 5: 5, 6: 4, 7: 3, 8: 2, 9: 1, 10: 0, 11: 0,
    12: 0, 13: 0, 14: 0, 15: 0, 16: 1, 17: 2, 18: 3, 19: 4,
}
_GRID_H = _TOP_CLEARANCE + 22 + 3  # body rows + 3 ground rows

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
    # `row` is relative to _TOP_CLEARANCE -- every shaping helper below
    # takes "row 0 = the ear tip" coordinates so they read the same as
    # they did before the clearance rows existed for the tail.
    grid[row + _TOP_CLEARANCE][col] = color
    grid[row + _TOP_CLEARANCE][_GRID_W - 1 - col] = color


def _raw(grid, row: int, col: int, color: str) -> None:
    grid[row + _TOP_CLEARANCE][col] = color


def _fill(grid, row: int, left_start: int, color: str = _F, right_edge: int = _HALF) -> None:
    # Default right_edge is _HALF (not _HALF - 1): mirroring up to
    # _HALF - 1 leaves the true center column (mirror of itself)
    # unfilled, which showed up as a spurious 1-pixel outline seam
    # running down the middle of the head once _apply_outline ran.
    for x in range(left_start, right_edge + 1):
        grid[row + _TOP_CLEARANCE][x] = color
        grid[row + _TOP_CLEARANCE][_GRID_W - 1 - x] = color


def _fill_with_tail_gap(grid, row: int, left_start: int, color: str = _F) -> None:
    # Like _fill, but for rows wide enough that a plain mirror would
    # reach into the tail's reserved gap on the right.
    for x in range(left_start, _HALF):
        grid[row + _TOP_CLEARANCE][x] = color
    for x in range(_HALF, _GRID_W - _TAIL_GAP):
        grid[row + _TOP_CLEARANCE][x] = color


def _build_base_grid(eyes_closed: bool, tail_raised: bool) -> list[list[str | None]]:
    """The round, chubby cat silhouette shared by every pose: small
    ears (pink inside both, a dark outer patch on one), one continuous
    round body, a dark patch flowing from the top of the head down the
    right side into the tail, four small feet with real gaps between
    each, a tail (tucked away for sleep, or a tall column rising past
    the ears otherwise), and a ground mound underneath. Only the eyes
    and the tail vary here; wake/dance widen the eyes further on top.
    """

    grid = _new_grid()

    # the silhouette, both ears and the whole body, all one fur color
    # for now -- the asymmetric dark patch and every face feature are
    # layered on afterward, in that order, so each one always shows up
    # correctly regardless of what's underneath
    _set(grid, 0, 7, _F)
    _fill(grid, 1, 6, right_edge=8)
    _fill(grid, 2, 6, right_edge=9)
    for row, start in _BODY_WIDTHS.items():
        if start <= 1:
            _fill_with_tail_gap(grid, row, start)
        else:
            _fill(grid, row, start)

    # the dark patch: everything right of center -- ear, head, and
    # body alike -- recolored in one pass. This is deliberately
    # computed from whatever's already filled at each row, rather than
    # a hand-picked column range per row: a hand-picked range that
    # doesn't exactly match the silhouette's actual taper is what
    # created an ugly flat "shelf" where the ear met the head in the
    # previous version. Reading it off the real silhouette guarantees
    # the patch edge always follows the body's actual outline.
    center = _GRID_W // 2
    for row in grid:
        for c in range(center, _GRID_W):
            if row[c] == _F:
                row[c] = _D

    # pink inner ear, on both sides regardless of the patch above
    _set(grid, 1, 7, _P)
    _set(grid, 2, 7, _P)

    # eyes: plain and simple, a closed line for sleep or a small dark
    # oval when open
    if eyes_closed:
        _set(grid, 8, 7, _PUPIL)
        _set(grid, 8, 8, _PUPIL)
    else:
        for row in (7, 8):
            _set(grid, row, 7, _PUPIL)
            _set(grid, row, 8, _PUPIL)

    # nose: a small solid vertical bar, centered just below the eyes --
    # direct assignment for the middle column too, since _set's mirror
    # alone would leave a gap between columns 11 and 13
    for row in (9, 10):
        for col in (11, 12, 13):
            _raw(grid, row, col, _P)

    # mouth: two small dots just under the nose -- a minimal
    # ":3"-style kitty smile, the one thing missing that most made the
    # face read as blank rather than a cat's
    _set(grid, 11, 10, _D)

    # four small dark feet, with a real gap between each pair so the
    # outline pass (see _apply_outline) separates them visually
    _fill(grid, 20, 4, color=_D, right_edge=5)
    _fill(grid, 20, 8, color=_D, right_edge=9)
    _fill(grid, 21, 4, color=_D, right_edge=5)
    _fill(grid, 21, 8, color=_D, right_edge=9)

    # tail: tucked away (hidden behind the body) for sleep, or a thick
    # column rising clearly past the ears -- into the blank clearance
    # rows above them -- for everything else, with a lighter banded tip
    if tail_raised:
        for row in range(-_TOP_CLEARANCE, 15):
            _raw(grid, row, _GRID_W - 2, _D)
            _raw(grid, row, _GRID_W - 3, _D)
        _raw(grid, -_TOP_CLEARANCE, _GRID_W - 2, _F)
        _raw(grid, -_TOP_CLEARANCE, _GRID_W - 3, _F)
        _raw(grid, -_TOP_CLEARANCE + 1, _GRID_W - 2, _F)
    else:
        _raw(grid, 14, _GRID_W - 3, _D)
        _raw(grid, 15, _GRID_W - 2, _D)

    # the ground mound the cat sits on -- the last 3 rows of the grid
    for offset, inset in enumerate((3, 1, 0)):
        for x in range(inset, _GRID_W - inset):
            grid[_GRID_H - 3 + offset][x] = _GROUND

    return grid


def _widen_eyes(grid) -> None:
    """A small light-colored glint in the corner of one eye -- used
    for wake/stretch/dance, layered on top of the shared base grid's
    already-open eyes to give a wide-eyed "just woke up" sparkle.
    (Previously this used the nose's pink, which overwrote part of
    the eye itself rather than adding a highlight to it.)
    """

    grid[_TOP_CLEARANCE + 7][8] = _HIGHLIGHT


def _sparkle(grid, row: int, col: int) -> None:
    grid[row][col] = _SPARKLE


def _apply_outline(grid) -> None:
    """Adds a 1-cell dark outline around every filled shape -- any
    background cell touching a filled one becomes outline-colored.
    This is what actually sells the "crisp pixel-art sprite" look: run
    without it, every shape bleeds into its neighbor (ears into head,
    legs into each other, the tail into the body) and the whole thing
    reads as a formless blob rather than distinct parts.
    """

    additions = []
    height = len(grid)
    for y in range(height):
        row = grid[y]
        for x in range(_GRID_W):
            if row[x] is not None:
                continue
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < _GRID_W and grid[ny][nx] is not None:
                    additions.append((y, x))
                    break
    for y, x in additions:
        grid[y][x] = _OUTLINE


def _rgba_bytes(hex_color: str) -> bytes:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return bytes((r, g, b, 255))


# Precomputed once at import time, not per frame.
_RGBA_CACHE: dict[str, bytes] = {}


def _grid_to_image(grid, y_offset: int = 0) -> QImage:
    # Writes raw RGBA bytes into a buffer and builds the QImage from
    # that in a single call, rather than looping hundreds of
    # `QPainter.drawRect()`/`QImage.setPixelColor()` calls per frame.
    # That per-cell-call approach -- even with QColor objects cached
    # and reused -- triggered a real, repeatable native refcount crash
    # in this environment's PySide6 build after only a few thousand
    # such calls across the process's lifetime (confirmed directly: a
    # tight loop of bare `image.setPixelColor()` calls with a single
    # reused QColor crashed the same way, so it's the call volume
    # itself, not anything specific to colors or QPainter). A single
    # QImage-from-buffer construction per frame doesn't cross the
    # Python/C++ boundary per pixel, so it doesn't accumulate the
    # same way; confirmed with 3000+ iterations and no crash.
    height = len(grid)
    row_bytes = bytearray(_GRID_W * 4)
    buf = bytearray(_GRID_W * height * 4)
    for y, row in enumerate(grid):
        dest_y = y + y_offset
        if not (0 <= dest_y < height):
            continue
        row_bytes[:] = b"\x00" * len(row_bytes)
        for x, color in enumerate(row):
            if color is None:
                continue
            rgba = _RGBA_CACHE.get(color)
            if rgba is None:
                rgba = _rgba_bytes(color)
                _RGBA_CACHE[color] = rgba
            row_bytes[x * 4 : x * 4 + 4] = rgba
        start = dest_y * _GRID_W * 4
        buf[start : start + len(row_bytes)] = row_bytes
    return QImage(bytes(buf), _GRID_W, height, _GRID_W * 4, QImage.Format.Format_RGBA8888).copy()


def _draw_cat(pose: str, frame: int) -> tuple[list[list[str | None]], int]:
    if pose == "sleep":
        grid = _build_base_grid(eyes_closed=True, tail_raised=False)
        y_offset = -1 if frame % 2 else 0
        # a little "z" that climbs up and to the right over the 4-frame
        # sleep cycle (small and low -> medium -> big and high), then
        # disappears for a beat before starting over
        if frame == 1:
            grid[_TOP_CLEARANCE + 3][16] = _PUPIL
            grid[_TOP_CLEARANCE + 3][17] = _PUPIL
        elif frame == 2:
            grid[_TOP_CLEARANCE + 2][18] = _PUPIL
            grid[_TOP_CLEARANCE + 2][19] = _PUPIL
            grid[_TOP_CLEARANCE + 1][17] = _PUPIL
            grid[_TOP_CLEARANCE + 1][18] = _PUPIL
        elif frame == 3:
            for col in (18, 19, 20, 21):
                grid[_TOP_CLEARANCE + 0][col] = _PUPIL
            grid[_TOP_CLEARANCE + 1][20] = _PUPIL
            grid[_TOP_CLEARANCE + 1][21] = _PUPIL
        _apply_outline(grid)
        return grid, y_offset
    elif pose == "wake":
        grid = _build_base_grid(eyes_closed=False, tail_raised=True)
        _widen_eyes(grid)
        _apply_outline(grid)
        return grid, 0
    elif pose == "stretch":
        grid = _build_base_grid(eyes_closed=frame == 0, tail_raised=True)
        if frame == 1:
            _widen_eyes(grid)
        _apply_outline(grid)
        return grid, 0
    else:  # dance
        grid = _build_base_grid(eyes_closed=False, tail_raised=True)
        _widen_eyes(grid)
        if frame % 2 == 0:
            _sparkle(grid, 0, 0)
        _apply_outline(grid)
        lift = 1 if frame % 2 else 0
        return grid, -lift


def _render_frame(pose: str, frame: int) -> QPixmap:
    grid, y_offset = _draw_cat(pose, frame)
    image = _grid_to_image(grid, y_offset)
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
