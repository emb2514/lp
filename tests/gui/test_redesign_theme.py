"""Tests for the pink/coral/orange/purple redesign: the sidebar's brand
mark and gradient, and the drop zone's gradient accent bar and icon
badge. Real user request: "lets go with Bold Rail, but make the
sidebar colors a little bit paler. Also please use the same font as
the Minimal Editorial [concept]" -- picking one of three mockup
concepts explored on a design canvas, then implementing it in the real
app (gui/theme.py's QSS, main_window.py's sidebar, drop_zone.py).
"""

from __future__ import annotations

from lender_package_builder.gui import theme
from lender_package_builder.gui.svg_render import render_svg_pixmap


# ---------------------------------------------------------------------
# svg_render.render_svg_pixmap -- no Qt widgets, just rasterization
# ---------------------------------------------------------------------


def test_render_svg_pixmap_from_file(tmp_path, qtbot):
    # `qtbot` isn't otherwise used here -- requesting it is what makes
    # pytest-qt construct the QApplication this needs, in case this is
    # the first test in the process to touch any Qt painting.
    svg_path = tmp_path / "shape.svg"
    svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                         '<rect width="10" height="10" fill="#F15D5D"/></svg>')

    pixmap = render_svg_pixmap(svg_path, 32)

    assert not pixmap.isNull()
    assert pixmap.size().width() == 64  # rendered at 2x for HiDPI
    assert pixmap.devicePixelRatio() == 2.0


def test_render_svg_pixmap_from_inline_markup(qtbot):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5"/></svg>'

    pixmap = render_svg_pixmap(svg, 20)

    assert not pixmap.isNull()
    assert pixmap.size().width() == 40


# ---------------------------------------------------------------------
# theme.py -- new tokens exist and are wired into the stylesheet
# ---------------------------------------------------------------------


def test_stylesheet_uses_the_brand_gradient_for_the_primary_button():
    css = theme.build_stylesheet()
    assert theme.BRAND_GRADIENT_CSS in css
    assert "QPushButton#PrimaryButton" in css


def test_stylesheet_uses_the_pale_gradient_for_the_sidebar():
    css = theme.build_stylesheet()
    assert theme.SIDEBAR_GRADIENT_CSS in css
    assert "QFrame#Sidebar" in css


def test_stylesheet_applies_the_display_font_to_brand_headings():
    css = theme.build_stylesheet()
    # Both the main app title and the sidebar's brand mark pick up the
    # serif display stack -- the "same font as Minimal Editorial" ask.
    assert "QLabel#AppTitle" in css
    assert "QLabel#SidebarBrand" in css
    assert "Cambria" in css


def test_sidebar_text_color_is_dark_ink_not_white():
    # The pale sidebar gradient is too light for white text to stay
    # readable -- this was the whole point of "make it a little paler".
    assert theme.SIDEBAR_TEXT == "#3A2640"
    css = theme.build_stylesheet()
    assert theme.SIDEBAR_TEXT in css


# ---------------------------------------------------------------------
# MainWindow -- the sidebar's logo mark and brand label
# ---------------------------------------------------------------------


def test_sidebar_shows_a_logo_mark_and_brand_label(window):
    assert window.sidebar_logo.pixmap() is not None
    assert not window.sidebar_logo.pixmap().isNull()
    assert window.sidebar_brand_label.text() == "Document Merger"
    assert window.sidebar_brand_label.objectName() == "SidebarBrand"


# ---------------------------------------------------------------------
# DropZone -- the gradient accent bar and the icon badge
# ---------------------------------------------------------------------


def test_drop_zone_has_a_gradient_accent_bar(window):
    assert window.drop_zone.accent_bar.objectName() == "DropZoneAccentBar"
    assert window.drop_zone.accent_bar.height() == 6


def test_drop_zone_has_a_rendered_icon_badge(window):
    pixmap = window.drop_zone.icon_badge.pixmap()
    assert pixmap is not None
    assert not pixmap.isNull()
