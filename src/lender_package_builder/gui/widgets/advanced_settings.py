"""Collapsed-by-default advanced settings: the output-part maximums.

Ordinary users never need to touch this. It maps directly onto the
existing Stage 1 `AppConfig.max_pages_per_part` /
`max_size_mb_per_part` -- nothing new is introduced, and the labels
are explicit that these are ceilings, not target sizes.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..state import AdvancedSettingsValues

EXPLANATION_TEXT = (
    "These are upper boundaries, not exact target sizes. An output part is closed as soon as "
    "adding the next complete document would exceed either maximum -- parts may finish well "
    "below either value. A complete source document is never split to fit a part. A single "
    "source document that alone exceeds a maximum is kept intact in its own oversized part. "
    "A package totaling 3,000+ pages is valid and will simply create as many parts as needed."
)


class AdvancedSettingsWidget(QWidget):
    def __init__(
        self, default_max_pages: int, default_max_size_mb: float, parent: QWidget | None = None
    ):
        super().__init__(parent)
        self._default_max_pages = default_max_pages
        self._default_max_size_mb = default_max_size_mb

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("AdvancedToggle")
        self.toggle_button.setText("▸ Advanced Settings")
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(False)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.toggled.connect(self._on_toggled)
        outer.addWidget(self.toggle_button)

        self.content = QFrame()
        self.content.setObjectName("Card")
        self.content.setVisible(False)
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(18, 16, 18, 16)
        content_layout.setSpacing(10)

        explanation = QLabel(EXPLANATION_TEXT)
        explanation.setObjectName("MutedLabel")
        explanation.setWordWrap(True)
        content_layout.addWidget(explanation)

        form = QFormLayout()
        form.setSpacing(8)

        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setRange(0, 1_000_000)
        self.max_pages_spin.setValue(default_max_pages)
        self.max_pages_spin.setSuffix(" pages")
        self.max_pages_spin.setToolTip(
            "Maximum pages allowed in one output part. A ceiling, not a target -- parts may finish below it."
        )
        form.addRow("Maximum pages per output part", self.max_pages_spin)

        self.max_size_spin = QDoubleSpinBox()
        self.max_size_spin.setRange(0.0, 1_000_000.0)
        self.max_size_spin.setDecimals(1)
        self.max_size_spin.setValue(default_max_size_mb)
        self.max_size_spin.setSuffix(" MB")
        self.max_size_spin.setToolTip(
            "Maximum size allowed in one output part. A ceiling, not a target -- parts may finish below it."
        )
        form.addRow("Maximum size per output part (MB)", self.max_size_spin)

        content_layout.addLayout(form)

        reset_row = QHBoxLayout()
        reset_row.addStretch(1)
        self.reset_button = QPushButton("Reset to recommended defaults")
        self.reset_button.clicked.connect(self.reset_to_defaults)
        reset_row.addWidget(self.reset_button)
        content_layout.addLayout(reset_row)

        self.validation_label = QLabel()
        self.validation_label.setObjectName("ValidationError")
        self.validation_label.setWordWrap(True)
        self.validation_label.hide()
        content_layout.addWidget(self.validation_label)

        outer.addWidget(self.content)

    def _on_toggled(self, checked: bool) -> None:
        self.content.setVisible(checked)
        self.toggle_button.setText(("▾" if checked else "▸") + " Advanced Settings")

    def is_expanded(self) -> bool:
        return self.toggle_button.isChecked()

    def reset_to_defaults(self) -> None:
        self.max_pages_spin.setValue(self._default_max_pages)
        self.max_size_spin.setValue(self._default_max_size_mb)
        self.validation_label.hide()

    def get_values(self) -> AdvancedSettingsValues:
        return AdvancedSettingsValues(
            max_pages_per_part=self.max_pages_spin.value(),
            max_size_mb_per_part=self.max_size_spin.value(),
        )

    def validate(self) -> tuple[bool, str]:
        if self.max_pages_spin.value() <= 0:
            message = "Maximum pages per output part must be a positive whole number."
            self.validation_label.setText(message)
            self.validation_label.show()
            # Auto-expand so a validation error is never hidden inside a
            # collapsed section the user can't see.
            self.toggle_button.setChecked(True)
            return False, message
        if self.max_size_spin.value() <= 0:
            message = "Maximum size per output part (MB) must be a positive number."
            self.validation_label.setText(message)
            self.validation_label.show()
            self.toggle_button.setChecked(True)
            return False, message
        self.validation_label.hide()
        return True, ""
