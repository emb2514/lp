"""Collapsed-by-default advanced settings: the output-part maximums.

Ordinary users never need to touch this. It maps directly onto the
existing Stage 1 `AppConfig.max_pages_per_part` /
`max_size_mb_per_part` -- nothing new is introduced, and the labels
are explicit that these are ceilings, not target sizes.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ... import naming
from ...models import PackageIdentity
from ..state import AdvancedSettingsValues

PACKAGE_DETAILS_HINT_TEXT = (
    "Fill these in ahead of time so Build starts right away -- they name the output folder and "
    "the package files. Automatic document recognition never supplies these on its own."
)

EXPLANATION_TEXT = (
    "These are upper boundaries, not exact target sizes. An output part is closed as soon as "
    "adding the next complete document would exceed either maximum -- parts may finish well "
    "below either value. A complete source document is never split to fit a part. A single "
    "source document that alone exceeds a maximum is kept intact in its own oversized part. "
    "A package totaling 3,000+ pages is valid and will simply create as many parts as needed."
)

CONTENT_AWARE_DEDUP_TOOLTIP = (
    "When enabled (recommended), the app also looks for duplicates that are not byte-for-byte "
    "identical -- e.g. the same document re-saved, or the same PDF with different metadata -- "
    "using content comparison, never filename or file size. Uncertain matches are always kept, "
    "never silently removed. Turning this off falls back to exact-byte-hash duplicate detection "
    "only, exactly like earlier versions of this app."
)


class AdvancedSettingsWidget(QWidget):
    def __init__(
        self,
        default_max_pages: int,
        default_max_size_mb: float,
        default_enable_content_aware_dedup: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._default_max_pages = default_max_pages
        self._default_max_size_mb = default_max_size_mb
        self._default_enable_content_aware_dedup = default_enable_content_aware_dedup

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

        package_details_heading = QLabel("Package Details")
        package_details_heading.setObjectName("SectionHeading")
        content_layout.addWidget(package_details_heading)

        package_details_hint = QLabel(PACKAGE_DETAILS_HINT_TEXT)
        package_details_hint.setObjectName("MutedLabel")
        package_details_hint.setWordWrap(True)
        content_layout.addWidget(package_details_hint)

        identity_form = QFormLayout()
        identity_form.setSpacing(8)
        identity_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self.last_name_edit = QLineEdit()
        self.last_name_edit.setPlaceholderText("Required, e.g. True")
        identity_form.addRow("Last name:", self.last_name_edit)

        self.first_name_edit = QLineEdit()
        self.first_name_edit.setPlaceholderText("e.g. Michael")
        identity_form.addRow("First name:", self.first_name_edit)

        self.loan_number_edit = QLineEdit()
        self.loan_number_edit.setPlaceholderText("e.g. 6192278785")
        identity_form.addRow("Loan number:", self.loan_number_edit)

        content_layout.addLayout(identity_form)

        self.adverse_checkbox = QCheckBox(
            "This is an adverse, withdrawn, denied, or cancelled (non-proceeding) file"
        )
        content_layout.addWidget(self.adverse_checkbox)

        identity_preview_caption = QLabel("Output folder will be named:")
        identity_preview_caption.setObjectName("MutedLabel")
        content_layout.addWidget(identity_preview_caption)

        self.identity_preview_label = QLabel()
        self.identity_preview_label.setObjectName("SectionHeading")
        self.identity_preview_label.setWordWrap(True)
        content_layout.addWidget(self.identity_preview_label)

        for edit in (self.last_name_edit, self.first_name_edit, self.loan_number_edit):
            edit.textChanged.connect(self._update_identity_preview)
        self.adverse_checkbox.toggled.connect(self._update_identity_preview)
        self._update_identity_preview()

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        content_layout.addWidget(divider)

        explanation = QLabel(EXPLANATION_TEXT)
        explanation.setObjectName("MutedLabel")
        explanation.setWordWrap(True)
        content_layout.addWidget(explanation)

        form = QFormLayout()
        form.setSpacing(8)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

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

        self.content_aware_dedup_checkbox = QCheckBox("Enable content-aware duplicate detection")
        self.content_aware_dedup_checkbox.setChecked(default_enable_content_aware_dedup)
        self.content_aware_dedup_checkbox.setToolTip(CONTENT_AWARE_DEDUP_TOOLTIP)
        content_layout.addWidget(self.content_aware_dedup_checkbox)

        content_aware_dedup_hint = QLabel(
            "Recommended: on. Turning this off falls back to exact-byte-hash duplicate detection only."
        )
        content_aware_dedup_hint.setObjectName("MutedLabel")
        content_aware_dedup_hint.setWordWrap(True)
        content_layout.addWidget(content_aware_dedup_hint)

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
        self.content_aware_dedup_checkbox.setChecked(self._default_enable_content_aware_dedup)
        self.validation_label.hide()

    def get_values(self) -> AdvancedSettingsValues:
        return AdvancedSettingsValues(
            max_pages_per_part=self.max_pages_spin.value(),
            max_size_mb_per_part=self.max_size_spin.value(),
            enable_content_aware_dedup=self.content_aware_dedup_checkbox.isChecked(),
        )

    def get_identity(self) -> PackageIdentity:
        return PackageIdentity(
            last_name=self.last_name_edit.text(),
            first_name=self.first_name_edit.text(),
            loan_number=self.loan_number_edit.text(),
            is_adverse=self.adverse_checkbox.isChecked(),
        )

    def set_identity(self, identity: PackageIdentity) -> None:
        self.last_name_edit.setText(identity.last_name)
        self.first_name_edit.setText(identity.first_name)
        self.loan_number_edit.setText(identity.loan_number)
        self.adverse_checkbox.setChecked(identity.is_adverse)

    def _update_identity_preview(self) -> None:
        self.identity_preview_label.setText(naming.main_folder_name(self.get_identity()))

    def validate(self) -> tuple[bool, str]:
        if not naming.sanitize_component(self.last_name_edit.text()):
            message = "Last name is required in Package Details -- it names the output folder and package files."
            self.validation_label.setText(message)
            self.validation_label.show()
            self.toggle_button.setChecked(True)
            return False, message
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
