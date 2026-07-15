"""Generates `packaging/app_icon.ico`, a multi-resolution Windows icon,
from the single `app_icon.svg` mark already used throughout the GUI
(window icon, About dialog). One source of artwork -- the desktop
icon, taskbar icon, and Explorer icon all show the same mark the
running application does.

Run manually with `python packaging/generate_icon.py`, or let
`BUILD_WINDOWS_PORTABLE.bat` / `LenderPackageBuilder.spec` regenerate
it automatically whenever the .ico is missing or older than the
source .svg.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = REPO_ROOT / "src" / "lender_package_builder" / "gui" / "assets" / "app_icon.svg"
ICO_PATH = REPO_ROOT / "packaging" / "app_icon.ico"

# Windows uses different sizes in different places: 16/32 for the
# taskbar and title bar, 48 for the desktop, 256 for Explorer's
# large-icon / jumbo view.
_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _rasterize(app, svg_path: Path, size: int):
    from PySide6.QtCore import QBuffer, QIODevice, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise ValueError(f"Could not parse SVG as valid: {svg_path}")

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def generate_icon() -> Path:
    if not SVG_PATH.exists():
        raise FileNotFoundError(f"Source icon SVG not found: {SVG_PATH}")

    import os

    from PIL import Image
    from PySide6.QtWidgets import QApplication

    if "QT_QPA_PLATFORM" not in os.environ and sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    app = QApplication.instance() or QApplication([sys.argv[0] if sys.argv else "generate_icon"])

    frames = []
    for size in _SIZES:
        png_bytes = _rasterize(app, SVG_PATH, size)
        frames.append(Image.open(io.BytesIO(png_bytes)).convert("RGBA"))

    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    largest = frames[-1]
    largest.save(
        ICO_PATH,
        format="ICO",
        sizes=[(f.width, f.height) for f in frames],
        append_images=frames[:-1],
    )
    return ICO_PATH


def main() -> int:
    try:
        path = generate_icon()
    except Exception as exc:
        print(f"ERROR: could not generate the application icon: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {path} ({len(_SIZES)} resolutions: {list(_SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
