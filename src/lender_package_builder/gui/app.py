"""GUI application bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .theme import apply_theme, configure_high_dpi


def create_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        configure_high_dpi()
        app = QApplication(sys.argv)
    apply_theme(app)
    return app


def run() -> int:
    app = create_app()
    window = MainWindow()
    window.show()
    return app.exec()
