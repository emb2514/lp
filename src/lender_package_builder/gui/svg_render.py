"""Rasterizes SVG markup or files into a `QPixmap`, at 2x resolution so
it stays crisp on HiDPI displays. Lets the sidebar logo and the drop
zone's icon badge reuse real SVG artwork (the actual `app_icon.svg` for
the former) instead of a second, hand-maintained icon representation.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_RENDER_SCALE = 2.0


def render_svg_pixmap(source: str | Path, size: int) -> QPixmap:
    """`source` is an SVG file path, or a `str` of raw SVG markup.
    Returns a square pixmap `size` x `size` logical pixels.
    """

    renderer = QSvgRenderer(str(source)) if isinstance(source, Path) else QSvgRenderer(QByteArray(source.encode("utf-8")))

    physical_size = int(size * _RENDER_SCALE)
    image = QImage(physical_size, physical_size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(_RENDER_SCALE)
    return pixmap
