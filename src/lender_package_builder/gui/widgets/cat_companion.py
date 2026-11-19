"""A small pixel-art cat that sits in the corner of the screen while a
build runs, then walks to the middle of the screen and celebrates with
a little floating heart when the build finishes -- staying there until
clicked, at which point it brings the main window to the front and
disappears in a puff.

Real user request, evolved over several rounds: "add a little pop up
notification for when its done. the pop up should be a pixelated cat
or smth" -- then, after multiple attempts at a hand-drawn sprite never
quite landing, "can you just find pixelated ones already created that
can be used? like someone else already made one and I can use it
without repercussions." The cat (idle + walk cycle) is "cute kitty
animated set" by kotnaszynce on OpenGameArt, CC0/public domain,
recolored to a grey tabby with a top-to-bottom ombre. The heart is a
CC0 emote-bubble sheet's heart row (kept with its speech-bubble frame,
per request). The poof is hand-drawn here, modeled on a reference
image, since no pixel-art poof turned up at the right tiny scale and
mixing in a smooth/anti-aliased found effect would have clashed with
the pixel-art sprites.

Final flow, confirmed with the user before building:
    - processing starts -> cat appears in the corner, idle loop
    - processing finishes -> cat walks to the middle of the screen
    - arrives -> a little heart appears above it, beating
    - cat sits there (idle + beating heart) until clicked
    - click -> brings the main window to the front, cat poofs away
    - stays gone until the next batch starts processing
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap, QTransform
from PySide6.QtWidgets import QLabel, QWidget

from ... import runtime_paths

# NOT `Path(__file__).resolve().parent.parent / "assets" / "cat"` -- that
# resolves correctly in source/dev mode, but `__file__` for a module
# bundled inside PyInstaller's compiled archive does not point to a
# real path on disk, so it silently failed to find any sprite in the
# packaged .exe (every QPixmap loaded null, so nothing ever painted --
# the cat was there, just invisible). `bundled_assets_root()` is the
# same helper `main_window.py` already uses for `app_icon.svg` for
# exactly this reason.
_ASSET_DIR = runtime_paths.bundled_assets_root() / "gui" / "assets" / "cat"
_SCALE = 7

_IDLE_FRAMES = ["idle_0.png", "idle_1.png", "idle_2.png"]
_WALK_FRAMES = ["walk_0.png", "walk_1.png", "walk_2.png", "walk_3.png"]
_HEART_GROW_FRAMES = ["heart_0.png", "heart_1.png", "heart_2.png", "heart_3.png"]
_HEART_BEAT_FRAMES = ["heart_4.png", "heart_5.png", "heart_6.png", "heart_7.png"]
_POOF_FRAMES = ["poof_0.png", "poof_1.png", "poof_2.png", "poof_3.png", "poof_4.png"]

_IDLE_FRAME_MS = 450
_WALK_FRAME_MS = 140
_HEART_GROW_MS = 150
_HEART_BEAT_MS = 220
_POOF_FRAME_MS = 70  # fast -- a quick pop, not a lingering effect

_WALK_TICKS = 30  # position steps for the corner-to-center walk
_WALK_STEP_MS = 45  # ~1.35s total walk -- a stroll, not a dash
_WALK_TICKS_PER_FRAME = 2  # how many position ticks before the walk sprite advances a frame

# cat_label is sized to fit the largest sprite (the poof) so switching
# between sprite sets never requires resizing it; heart_label sits in
# its own reserved strip above that.
_CAT_SPRITE_PX = 16
_POOF_SPRITE_PX = 26
_HEART_SPRITE_PX = 16


def _pixmap_cache() -> dict[str, QPixmap]:
    # A lazily-created cache (not a module-level dict built at import
    # time) so pixmap loading only happens once a QApplication exists
    # -- constructing a QPixmap any earlier than that is unsafe.
    if not hasattr(_pixmap_cache, "_cache"):
        _pixmap_cache._cache = {}
    return _pixmap_cache._cache


def _load(name: str, native_px: int) -> QPixmap:
    cache = _pixmap_cache()
    cached = cache.get(name)
    if cached is not None:
        return cached
    raw = QPixmap(str(_ASSET_DIR / name))
    size = native_px * _SCALE
    scaled = raw.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation
    )
    cache[name] = scaled
    return scaled


def _load_flipped(name: str, native_px: int) -> QPixmap:
    key = f"flip:{name}"
    cache = _pixmap_cache()
    cached = cache.get(key)
    if cached is not None:
        return cached
    pix = _load(name, native_px).transformed(QTransform().scale(-1, 1))
    cache[key] = pix
    return pix


class CatCompanionWidget(QWidget):
    """Frameless, always-on-top companion. Call `start_idle()` once a
    build starts and `celebrate()` once it finishes successfully; the
    cat handles the walk, the heart, and poofing away on click itself.
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
        total_w = _POOF_SPRITE_PX * _SCALE
        total_h = (_POOF_SPRITE_PX + _HEART_SPRITE_PX) * _SCALE
        self.setFixedSize(total_w, total_h)

        self._heart_label = QLabel(self)
        self._heart_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._heart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._heart_label.setGeometry(0, 0, total_w, _HEART_SPRITE_PX * _SCALE)
        self._heart_label.hide()

        self._cat_label = QLabel(self)
        self._cat_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._cat_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cat_label.setGeometry(0, _HEART_SPRITE_PX * _SCALE, total_w, _POOF_SPRITE_PX * _SCALE)

        # one of "idle", "walking", "celebrating", "poofing", "hidden"
        self._state = "hidden"
        self._cat_frame = 0
        self._heart_frame = 0
        self._heart_phase = "grow"  # or "beat"
        self._flipped = False
        self._walk_tick = 0
        self._walk_start = QPoint()
        self._walk_target = QPoint()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance_cat)
        self._heart_timer = QTimer(self)
        self._heart_timer.timeout.connect(self._advance_heart)
        self._walk_timer = QTimer(self)
        self._walk_timer.timeout.connect(self._advance_walk)

    # -- public API ----------------------------------------------

    def start_idle(self) -> None:
        """Show the cat idling in the corner. Safe to call from any
        state -- a build starting always wins over whatever the cat
        was doing (mid-walk, celebrating, poofed away).
        """

        self._stop_all_timers()
        self._heart_label.hide()
        self._flipped = False
        self._place_in_corner()
        self._state = "idle"
        self._cat_frame = 0
        self._render_cat()
        self.show()
        self._timer.start(_IDLE_FRAME_MS)

    def celebrate(self) -> None:
        """Walk to the middle of the screen and show a beating heart.
        Called once a build finishes successfully.
        """

        if self._state == "hidden" or not self.isVisible():
            self.start_idle()
        self._stop_all_timers()
        self._heart_label.hide()
        # the walk sprite faces right by default; flip it to face its
        # direction of travel (the corner is bottom-right, center is
        # up-and-left of that)
        self._flipped = True
        self._state = "walking"
        self._cat_frame = 0
        self._walk_tick = 0
        self._walk_start = self.pos()
        self._walk_target = self._center_target_pos()
        self._render_cat()
        self._walk_timer.start(_WALK_STEP_MS)

    # -- internals ----------------------------------------------

    def _stop_all_timers(self) -> None:
        self._timer.stop()
        self._heart_timer.stop()
        self._walk_timer.stop()

    def _place_in_corner(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        margin = 18
        self.move(geo.right() - self.width() - margin, geo.bottom() - self.height() - margin)

    def _center_target_pos(self) -> QPoint:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return self.pos()
        geo = screen.availableGeometry()
        # Center the CAT sprite itself on the screen, not the whole
        # envelope (which reserves extra space above it for the heart).
        cat_size = _CAT_SPRITE_PX * _SCALE
        x = geo.center().x() - self.width() // 2
        y = geo.center().y() - _HEART_SPRITE_PX * _SCALE - cat_size // 2
        return QPoint(x, y)

    def _render_cat(self) -> None:
        if self._state in ("idle", "celebrating"):
            name = _IDLE_FRAMES[self._cat_frame % len(_IDLE_FRAMES)]
            native_px = _CAT_SPRITE_PX
        elif self._state == "walking":
            name = _WALK_FRAMES[self._cat_frame % len(_WALK_FRAMES)]
            native_px = _CAT_SPRITE_PX
        elif self._state == "poofing":
            name = _POOF_FRAMES[min(self._cat_frame, len(_POOF_FRAMES) - 1)]
            native_px = _POOF_SPRITE_PX
        else:
            return
        pix = _load_flipped(name, native_px) if self._flipped else _load(name, native_px)
        self._cat_label.setPixmap(pix)

    def _render_heart(self) -> None:
        frames = _HEART_GROW_FRAMES if self._heart_phase == "grow" else _HEART_BEAT_FRAMES
        name = frames[self._heart_frame % len(frames)]
        self._heart_label.setPixmap(_load(name, _HEART_SPRITE_PX))

    def _advance_cat(self) -> None:
        # Drives whichever cat animation is active via self._timer:
        # idle/celebrating loop forever, poofing runs once and ends.
        if self._state == "poofing":
            self._cat_frame += 1
            if self._cat_frame >= len(_POOF_FRAMES):
                self._timer.stop()
                self._state = "hidden"
                self.hide()
                return
            self._render_cat()
            return
        self._cat_frame += 1
        self._render_cat()

    def _advance_walk(self) -> None:
        self._walk_tick += 1
        t = min(1.0, self._walk_tick / _WALK_TICKS)
        x = round(self._walk_start.x() + (self._walk_target.x() - self._walk_start.x()) * t)
        y = round(self._walk_start.y() + (self._walk_target.y() - self._walk_start.y()) * t)
        self.move(x, y)
        self._cat_frame = self._walk_tick // _WALK_TICKS_PER_FRAME
        self._render_cat()
        if t >= 1.0:
            self._walk_timer.stop()
            self._start_celebrating()

    def _start_celebrating(self) -> None:
        self._state = "celebrating"
        self._cat_frame = 0
        self._render_cat()
        self._timer.start(_IDLE_FRAME_MS)

        self._heart_phase = "grow"
        self._heart_frame = 0
        self._render_heart()
        self._heart_label.show()
        self._heart_timer.start(_HEART_GROW_MS)

    def _advance_heart(self) -> None:
        self._heart_frame += 1
        if self._heart_phase == "grow" and self._heart_frame >= len(_HEART_GROW_FRAMES):
            self._heart_phase = "beat"
            self._heart_frame = 0
            self._heart_timer.start(_HEART_BEAT_MS)
        self._render_heart()

    def _poof_away(self) -> None:
        """Play the poof animation once, then hide until the next
        `start_idle()` call. Only meaningful while celebrating -- a
        click during idle (mid-build) just brings the window forward.
        """

        self._stop_all_timers()
        self._heart_label.hide()
        self._flipped = False
        self._state = "poofing"
        self._cat_frame = 0
        self._render_cat()
        self._timer.start(_POOF_FRAME_MS)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._parent_window is not None:
            self._parent_window.show()
            self._parent_window.raise_()
            self._parent_window.activateWindow()
        if self._state == "celebrating":
            self._poof_away()
        super().mousePressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        # A separate top-level, always-on-top widget with its own
        # running timers -- closing it must stop them, not just hide
        # the window, or the animation loops keep firing indefinitely
        # against a widget nothing else references.
        self._stop_all_timers()
        super().closeEvent(event)
