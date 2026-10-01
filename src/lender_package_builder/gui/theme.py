"""Visual theme: color palette, fonts, and the application stylesheet.

A warm pink/coral/orange/purple brand gradient (the same one used in
`gui/assets/app_icon.svg`), a light neutral background, white cards,
rounded corners, and clear success/warning/error colors. No remote
fonts or assets are ever loaded -- everything here is a literal
color/QSS string compiled into the app; the one serif display font
used for headings is a system font stack, not a bundled/downloaded
font file.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

BACKGROUND = "#FAFAFA"
CARD_BACKGROUND = "#FFFFFF"
CARD_BORDER = "#E2E6EA"

# Solid accent (links, focus/hover borders, progress bar) -- the deep
# purple end of the brand gradient below.
ACCENT = "#883F8C"
ACCENT_HOVER = "#6B2F70"
ACCENT_PRESSED = "#52235A"
ACCENT_DISABLED = "#D8C3DA"

# The full brand gradient (pink -> coral -> orange -> purple), used
# wherever a gradient fill reads better than a flat color: the primary
# button, the drop zone's icon badge, the sidebar logo mark.
GRADIENT_PINK = "#F6A2B8"
GRADIENT_CORAL = "#F15D5D"
GRADIENT_ORANGE = "#F0B35A"
GRADIENT_PURPLE = "#883F8C"
BRAND_GRADIENT_CSS = (
    f"qlineargradient(x1:0, y1:0, x2:1, y2:1, "
    f"stop:0 {GRADIENT_PINK}, stop:0.35 {GRADIENT_CORAL}, stop:0.65 {GRADIENT_ORANGE}, stop:1 {GRADIENT_PURPLE})"
)
BRAND_GRADIENT_HOVER_CSS = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {GRADIENT_CORAL}, stop:1 {ACCENT_HOVER})"
BRAND_GRADIENT_HORIZONTAL_CSS = (
    f"qlineargradient(x1:0, y1:0, x2:1, y2:0, "
    f"stop:0 {GRADIENT_PINK}, stop:0.35 {GRADIENT_CORAL}, stop:0.65 {GRADIENT_ORANGE}, stop:1 {GRADIENT_PURPLE})"
)

# The sidebar's own paler version of the same four hues, plus the dark
# ink used for text/icons on top of it (the gradient is too light for
# white text to stay readable).
SIDEBAR_GRADIENT_CSS = (
    "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
    "stop:0 #F9C3D1, stop:0.38 #F69696, stop:0.68 #F5CE94, stop:1 #B282B4)"
)
SIDEBAR_TEXT = "#3A2640"
SIDEBAR_TEXT_MUTED = "rgba(58, 38, 64, 0.65)"
SIDEBAR_ACTIVE_BG = "rgba(255, 255, 255, 0.55)"
SIDEBAR_ACTIVE_BORDER = "#883F8C"
SIDEBAR_BADGE_BG = "rgba(255, 255, 255, 0.45)"
SIDEBAR_BADGE_BORDER = "rgba(58, 38, 64, 0.25)"

TEXT_PRIMARY = "#1F2733"
TEXT_SECONDARY = "#5B6673"
TEXT_ON_ACCENT = "#FFFFFF"

SUCCESS = "#1E8E3E"
SUCCESS_BG = "#E6F4EA"
WARNING = "#B7791F"
WARNING_BG = "#FEF3E2"
ERROR = "#C5221F"
ERROR_BG = "#FCE8E6"
DRAG_ACTIVE_BG = "#FDEEF2"

FONT_FAMILIES = ["Segoe UI", "Segoe UI Variable", "-apple-system", "Helvetica Neue", "Arial", "sans-serif"]

# A serif display stack for headings/brand text -- Cambria and Georgia
# ship with Windows/macOS by default, so this reads as an intentional
# editorial pairing without bundling a font file.
DISPLAY_FONT_FAMILIES = ["Cambria", "Georgia", "Constantia", "Times New Roman", "serif"]

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
    display_font_family = ", ".join(f'"{f}"' if " " in f else f for f in DISPLAY_FONT_FAMILIES)
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
        font-family: {display_font_family};
        font-size: 20pt;
        font-weight: 600;
        color: {TEXT_PRIMARY};
    }}

    QLabel#AppSubtitle {{
        font-size: 10.5pt;
        color: {TEXT_SECONDARY};
    }}

    QLabel#PrivacyBadge {{
        color: {SIDEBAR_TEXT};
        font-size: 9pt;
        font-weight: 700;
        padding: 5px 12px;
        border: 1px solid {SIDEBAR_BADGE_BORDER};
        border-radius: {RADIUS + 9}px;
        background: {SIDEBAR_BADGE_BG};
    }}

    QFrame#Card {{
        background: {CARD_BACKGROUND};
        border: 1px solid {CARD_BORDER};
        border-radius: {RADIUS}px;
    }}

    QFrame#DropZone {{
        background: {CARD_BACKGROUND};
        border: 1px solid {CARD_BORDER};
        border-radius: {RADIUS + 4}px;
    }}

    QFrame#DropZone[dragActive="true"] {{
        border: 1px solid {ACCENT};
        background: {DRAG_ACTIVE_BG};
    }}

    QFrame#DropZoneAccentBar {{
        background: {BRAND_GRADIENT_HORIZONTAL_CSS};
        border-top-left-radius: {RADIUS + 3}px;
        border-top-right-radius: {RADIUS + 3}px;
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
        background: {BRAND_GRADIENT_CSS};
        color: {TEXT_ON_ACCENT};
        border: none;
        font-weight: 600;
        padding: 10px 22px;
        font-size: 11pt;
    }}

    QPushButton#PrimaryButton:hover {{
        background: {BRAND_GRADIENT_HOVER_CSS};
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

    QFrame#ComparePageCell {{
        background: {CARD_BACKGROUND};
        border: 2px solid transparent;
        border-radius: {RADIUS}px;
    }}

    QFrame#ComparePageCell[unmatched="true"] {{
        background: {WARNING_BG};
        border: 2px solid {WARNING};
    }}

    QFrame#ComparePageCell:hover {{
        border: 2px solid {ACCENT};
    }}

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

    QFrame#Sidebar {{
        background: {SIDEBAR_GRADIENT_CSS};
        border-right: none;
    }}

    QLabel#SidebarBrand {{
        font-family: {display_font_family};
        font-style: italic;
        font-weight: 600;
        font-size: 12.5pt;
        color: {SIDEBAR_TEXT};
    }}

    QPushButton#NavButton {{
        text-align: left;
        border: none;
        border-left: 3px solid transparent;
        border-radius: {RADIUS - 2}px;
        padding: 9px 12px 9px 9px;
        font-weight: 600;
        color: {SIDEBAR_TEXT_MUTED};
        background: transparent;
    }}

    QPushButton#NavButton:hover {{
        background: rgba(255, 255, 255, 0.30);
        color: {SIDEBAR_TEXT};
    }}

    QPushButton#NavButton:checked {{
        background: {SIDEBAR_ACTIVE_BG};
        border-left: 3px solid {SIDEBAR_ACTIVE_BORDER};
        color: {SIDEBAR_TEXT};
    }}
    """
