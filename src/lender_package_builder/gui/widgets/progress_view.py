"""Progress panel: a persistent side panel (not a page that replaces
the input form) showing "Ready to build" before a run starts, live
status while one is running, and reverting to "Ready to build" once it
finishes -- the center content (input form / result / failure) is what
communicates the outcome of a finished run.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..formatting import format_elapsed
from .circular_progress import CircularProgressIndicator
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

        self.stage_label = QLabel("Ready to build")
        self.stage_label.setObjectName("SectionHeading")
        self.stage_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.stage_label)

        circle_row = QHBoxLayout()
        circle_row.addStretch(1)
        self.circular_indicator = CircularProgressIndicator()
        circle_row.addWidget(self.circular_indicator)
        circle_row.addStretch(1)
        card_layout.addLayout(circle_row)

        # The real progress data other code/tests read stays a normal
        # QProgressBar (hidden -- the circular indicator above is its
        # visual companion, driven from the same values).
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate until a real total arrives
        self.progress_bar.hide()
        card_layout.addWidget(self.progress_bar)

        self.count_label = QLabel("0 of 0 documents processed")
        self.count_label.setObjectName("MutedLabel")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.count_label)

        detail_form = QFormLayout()
        detail_form.setSpacing(4)
        self.current_step_label = QLabel("--")
        self.current_step_label.setWordWrap(True)
        detail_form.addRow("Current step:", self.current_step_label)

        self.current_item_label = QLabel("--")
        self.current_item_label.setObjectName("MutedLabel")
        self.current_item_label.setWordWrap(True)
        detail_form.addRow("Current doc:", self.current_item_label)
        card_layout.addLayout(detail_form)

        self.status_message_label = QLabel("")
        self.status_message_label.setWordWrap(True)
        card_layout.addWidget(self.status_message_label)

        time_row = QHBoxLayout()
        self.elapsed_label = QLabel("Elapsed time\n00:00")
        self.elapsed_label.setObjectName("MutedLabel")
        time_row.addWidget(self.elapsed_label)
        self.remaining_label = QLabel("Est. time remaining\n--")
        self.remaining_label.setObjectName("MutedLabel")
        self.remaining_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        time_row.addWidget(self.remaining_label)
        card_layout.addLayout(time_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = QPushButton("Cancel Processing")
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.cancel_button.hide()
        button_row.addWidget(self.cancel_button)
        card_layout.addLayout(button_row)

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
        self.circular_indicator.set_indeterminate()
        self.current_step_label.setText("Preparing")
        self.current_item_label.setText("--")
        self.count_label.setText("0 of 0 documents processed")
        self.status_message_label.setText("Starting...")
        self.activity_log.clear()
        self._elapsed_seconds = 0.0
        self.elapsed_label.setText("Elapsed time\n00:00")
        self.remaining_label.setText("Est. time remaining\n--")
        self.cancel_button.show()
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel Processing")
        self._timer.start()

    def set_cancelling(self) -> None:
        """Called once the user has confirmed Stop Processing -- disables
        the button (a cancellation request is a one-way, sticky flag; a
        second click has nothing new to do) and gives immediate visual
        feedback while the pipeline reaches its next safe check point.
        """

        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancelling...")

    def stop(self) -> None:
        """Stops the elapsed-time timer and returns the panel to its
        idle "Ready to build" state -- the center content (result view
        or failure view) is what communicates a finished run's outcome,
        so this panel is immediately ready for the next one.
        """

        self._timer.stop()
        self.stage_label.setText("Ready to build")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.circular_indicator.set_value(0)
        self.current_step_label.setText("--")
        self.current_item_label.setText("--")
        self.count_label.setText("0 of 0 documents processed")
        self.status_message_label.setText("")
        self.cancel_button.hide()

    def _tick(self) -> None:
        self._elapsed_seconds += 1
        self.elapsed_label.setText(f"Elapsed time\n{format_elapsed(self._elapsed_seconds)}")

    def handle_event(self, event: ProgressEvent) -> None:
        stage_text = STAGE_LABELS.get(event.stage, event.stage.value)
        self.stage_label.setText(stage_text)
        self.current_step_label.setText(stage_text)

        if event.total:
            self.progress_bar.setRange(0, event.total)
            self.progress_bar.setValue(event.current or 0)
            self.circular_indicator.set_value(round(100 * (event.current or 0) / event.total))
        elif event.stage == ProgressStage.COMPLETE:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.circular_indicator.set_value(100)
        else:
            self.progress_bar.setRange(0, 0)
            self.circular_indicator.set_indeterminate()

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
