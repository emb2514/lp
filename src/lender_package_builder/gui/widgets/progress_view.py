"""Processing view: shown while a build job is running."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QProgressBar, QVBoxLayout, QWidget

from ..formatting import format_elapsed
from ...progress import ProgressEvent, ProgressSeverity, ProgressStage

STAGE_LABELS = {
    ProgressStage.PREFLIGHT: "Preparing",
    ProgressStage.DISCOVERING_FILES: "Discovering files",
    ProgressStage.DETECTING_DUPLICATES: "Checking exact duplicates",
    ProgressStage.CONVERTING_DOCUMENTS: "Converting documents",
    ProgressStage.BUILDING_OG: "Creating OG package",
    ProgressStage.FINGERPRINTING_CONTENT: "Analyzing document content",
    ProgressStage.DETECTING_CONTENT_DUPLICATES: "Checking content duplicates",
    ProgressStage.ANALYZING_MERGED_PACKAGES: "Analyzing merged packages",
    ProgressStage.CLASSIFYING_VERSIONS: "Classifying document versions",
    ProgressStage.BUILDING_FINAL: "Creating Final package",
    ProgressStage.RUNNING_INTEGRITY_CHECKS: "Verifying output",
    ProgressStage.WRITING_REPORTS: "Writing reports",
    ProgressStage.COMPLETE: "Complete",
}

MAX_LOG_LINES = 500


class ProgressView(QWidget):
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

        self.stage_label = QLabel("Preparing")
        self.stage_label.setObjectName("SectionHeading")
        card_layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate until a real total arrives
        card_layout.addWidget(self.progress_bar)

        self.current_item_label = QLabel("")
        self.current_item_label.setObjectName("MutedLabel")
        self.current_item_label.setWordWrap(True)
        card_layout.addWidget(self.current_item_label)

        self.count_label = QLabel("")
        self.count_label.setObjectName("MutedLabel")
        card_layout.addWidget(self.count_label)

        self.status_message_label = QLabel("Starting...")
        card_layout.addWidget(self.status_message_label)

        self.elapsed_label = QLabel("Elapsed: 0s")
        self.elapsed_label.setObjectName("MutedLabel")
        card_layout.addWidget(self.elapsed_label)

        layout.addWidget(card)

        log_heading = QLabel("Recent activity")
        log_heading.setObjectName("SectionHeading")
        layout.addWidget(log_heading)

        self.activity_log = QPlainTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.document().setMaximumBlockCount(MAX_LOG_LINES)
        self.activity_log.setMinimumHeight(160)
        layout.addWidget(self.activity_log, stretch=1)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._elapsed_seconds = 0.0

    def start(self) -> None:
        self.stage_label.setText("Preparing")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.current_item_label.setText("")
        self.count_label.setText("")
        self.status_message_label.setText("Starting...")
        self.activity_log.clear()
        self._elapsed_seconds = 0.0
        self.elapsed_label.setText("Elapsed: 0s")
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._elapsed_seconds += 1
        self.elapsed_label.setText(f"Elapsed: {format_elapsed(self._elapsed_seconds)}")

    def handle_event(self, event: ProgressEvent) -> None:
        self.stage_label.setText(STAGE_LABELS.get(event.stage, event.stage.value))

        if event.total:
            self.progress_bar.setRange(0, event.total)
            self.progress_bar.setValue(event.current or 0)
        elif event.stage == ProgressStage.COMPLETE:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
        else:
            self.progress_bar.setRange(0, 0)

        if event.current_item:
            self.current_item_label.setText(f"Current file: {event.current_item}")
        if event.current is not None and event.total:
            self.count_label.setText(f"Document {event.current} of {event.total}")

        self.status_message_label.setText(event.message.strip())

        prefix = {
            ProgressSeverity.WARNING: "[Warning] ",
            ProgressSeverity.ERROR: "[Error] ",
        }.get(event.severity, "")
        self.activity_log.appendPlainText(f"{prefix}{event.message.strip()}")
