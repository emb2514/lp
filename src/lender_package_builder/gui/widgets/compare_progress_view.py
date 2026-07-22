"""Compare Packages progress screen: a lightweight status
message + indeterminate progress bar + elapsed timer + Cancel
Comparison button. Comparing a large package can take a while, so this
never freezes the interface -- the actual comparison always runs on a
background thread (see gui/worker.py's make_compare_callable).
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ..formatting import format_elapsed


class CompareProgressView(QWidget):
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(8)

        self.status_label = QLabel("Starting comparison...")
        card_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        card_layout.addWidget(self.progress_bar)

        self.warning_label = QLabel("Large packages may take several minutes to compare.")
        self.warning_label.setObjectName("MutedLabel")
        card_layout.addWidget(self.warning_label)

        self.elapsed_label = QLabel("Elapsed: 0s")
        self.elapsed_label.setObjectName("MutedLabel")
        card_layout.addWidget(self.elapsed_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = QPushButton("Cancel Comparison")
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        button_row.addWidget(self.cancel_button)
        card_layout.addLayout(button_row)

        layout.addWidget(card)
        layout.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._elapsed_seconds = 0.0

    def start(self) -> None:
        self.status_label.setText("Starting comparison...")
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel Comparison")
        self._elapsed_seconds = 0.0
        self.elapsed_label.setText("Elapsed: 0s")
        self._timer.start()

    def set_cancelling(self) -> None:
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancelling...")

    def stop(self) -> None:
        self._timer.stop()

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _tick(self) -> None:
        self._elapsed_seconds += 1
        self.elapsed_label.setText(f"Elapsed: {format_elapsed(self._elapsed_seconds)}")
