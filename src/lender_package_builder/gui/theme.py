"""Visual theme: color palette, fonts, and the application stylesheet.

One professional accent color (deep blue-teal), a light neutral
background, white cards, rounded corners, and clear success/warning/
error colors. No remote fonts or assets are ever loaded -- everything
here is a literal color/QSS string compiled into the app.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

BACKGROUND = "#F4F6F8"
CARD_BACKGROUND = "#FFFFFF"
CARD_BORDER = "#E2E6EA"

ACCENT = "#0E6E8C"
ACCENT_HOVER = "#0B5A73"
ACCENT_PRESSED = "#094859"
ACCENT_DISABLED = "#A9C4CD"

TEXT_PRIMARY = "#1F2733"
TEXT_SECONDARY = "#5B6673"
TEXT_ON_ACCENT = "#FFFFFF"

SUCCESS = "#1E8E3E"
SUCCESS_BG = "#E6F4EA"
WARNING = "#B7791F"
WARNING_BG = "#FEF3E2"
ERROR = "#C5221F"
ERROR_BG = "#FCE8E6"

FONT_FAMILIES = ["Segoe UI", "Segoe UI Variable", "-apple-system", "Helvetica Neue", "Arial", "sans-serif"]

RADIUS = 10


def configure_high_dpi() -> None:
    """Must be called BEFORE the QApplication instance is constructed."""

    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:  # pragma: no cover - depends on Qt version
        pass


def apply_theme(app: QApplication) -> None:
    """Apply the font and stylesheet to the whole application."""

    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSize(10)
    app.setFont(font)

    app.setStyleSheet(build_stylesheet())


def build_stylesheet() -> str:
    font_family = ", ".join(f'"{f}"' if " " in f else f for f in FONT_FAMILIES)
    return f"""
    QWidget {{
        background: {BACKGROUND};
        color: {TEXT_PRIMARY};
        font-family: {font_family};
        font-size: 10.5pt;
    }}

    QMainWindow {{
        background: {BACKGROUND};
    }}

    QLabel {{
        background: transparent;
    }}

    QLabel#AppTitle {{
        font-size: 19pt;
        font-weight: 600;
        color: {TEXT_PRIMARY};
    }}

    QLabel#AppSubtitle {{
        font-size: 10.5pt;
        color: {TEXT_SECONDARY};
    }}

    QLabel#PrivacyBadge {{
        color: {ACCENT};
        font-size: 9pt;
        font-weight: 600;
        padding: 3px 10px;
        border: 1px solid {ACCENT};
        border-radius: {RADIUS + 4}px;
        background: {CARD_BACKGROUND};
    }}

    QFrame#Card {{
        background: {CARD_BACKGROUND};
        border: 1px solid {CARD_BORDER};
        border-radius: {RADIUS}px;
    }}

    QFrame#DropZone {{
        background: {CARD_BACKGROUND};
        border: 2px dashed {CARD_BORDER};
        border-radius: {RADIUS + 4}px;
    }}

    QFrame#DropZone[dragActive="true"] {{
        border: 2px dashed {ACCENT};
        background: {SUCCESS_BG};
    }}

    QLabel#DropZoneTitle {{
        font-size: 13pt;
        font-weight: 600;
        color: {TEXT_PRIMARY};
    }}

    QLabel#DropZoneHint {{
        color: {TEXT_SECONDARY};
        font-size: 9.5pt;
    }}

    QPushButton {{
        background: {CARD_BACKGROUND};
        color: {TEXT_PRIMARY};
        border: 1px solid {CARD_BORDER};
        border-radius: {RADIUS - 2}px;
        padding: 7px 16px;
    }}

    QPushButton:hover {{
        border-color: {ACCENT};
    }}

    QPushButton:pressed {{
        background: {BACKGROUND};
    }}

    QPushButton#PrimaryButton {{
        background: {ACCENT};
        color: {TEXT_ON_ACCENT};
        border: none;
        font-weight: 600;
        padding: 10px 22px;
        font-size: 11pt;
    }}

    QPushButton#PrimaryButton:hover {{
        background: {ACCENT_HOVER};
    }}

    QPushButton#PrimaryButton:pressed {{
        background: {ACCENT_PRESSED};
    }}

    QPushButton#PrimaryButton:disabled {{
        background: {ACCENT_DISABLED};
        color: {TEXT_ON_ACCENT};
    }}

    QLabel#SectionHeading {{
        font-weight: 600;
        font-size: 11pt;
        color: {TEXT_PRIMARY};
    }}

    QLabel#MutedLabel {{
        color: {TEXT_SECONDARY};
    }}

    QFrame#StatusBanner[status="success"] {{
        background: {SUCCESS_BG};
        border: 1px solid {SUCCESS};
        border-radius: {RADIUS}px;
    }}

    QFrame#StatusBanner[status="warning"] {{
        background: {WARNING_BG};
        border: 1px solid {WARNING};
        border-radius: {RADIUS}px;
    }}

    QFrame#StatusBanner[status="error"] {{
        background: {ERROR_BG};
        border: 1px solid {ERROR};
        border-radius: {RADIUS}px;
    }}

    QLabel#StatusBannerTitle[status="success"] {{ color: {SUCCESS}; font-weight: 700; font-size: 13pt; }}
    QLabel#StatusBannerTitle[status="warning"] {{ color: {WARNING}; font-weight: 700; font-size: 13pt; }}
    QLabel#StatusBannerTitle[status="error"] {{ color: {ERROR}; font-weight: 700; font-size: 13pt; }}

    QProgressBar {{
        background: {BACKGROUND};
        border: 1px solid {CARD_BORDER};
        border-radius: {RADIUS - 2}px;
        text-align: center;
        min-height: 18px;
    }}

    QProgressBar::chunk {{
        background: {ACCENT};
        border-radius: {RADIUS - 3}px;
    }}

    QPlainTextEdit, QTextEdit {{
        background: {CARD_BACKGROUND};
        border: 1px solid {CARD_BORDER};
        border-radius: {RADIUS - 2}px;
    }}

    QToolButton {{
        border: none;
        color: {ACCENT};
        font-weight: 600;
        background: transparent;
    }}

    QSpinBox, QDoubleSpinBox {{
        background: {CARD_BACKGROUND};
        border: 1px solid {CARD_BORDER};
        border-radius: {RADIUS - 4}px;
        padding: 4px 6px;
        min-height: 22px;
    }}

    QLabel#ValidationError {{
        color: {ERROR};
        font-size: 9pt;
    }}
    """
