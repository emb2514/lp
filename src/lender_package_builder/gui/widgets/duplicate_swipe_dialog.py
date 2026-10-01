"""The "Review Possible Duplicates" dialog: a one-at-a-time, keyboard-
driven review of every document the engine EXCLUDED from Final as a
CONFIDENT duplicate/containment match.

This is deliberately separate from `UncertainReviewDialog`
("Review Uncertain Matches"), which covers matches the engine was NOT
confident about -- those are never auto-excluded in the first place, so
there is nothing to "triple check" there. This dialog covers the
opposite, and genuinely different, worry a real user raised: "i need to
tripple check we arent excluding documents because it could be a dupe...
kinda like those tinder type apps to delete duplicate pictures... press
enter for keep and delete for keeping it out of the final package."

Enter = restore this document into Final (it is not actually a
duplicate, or should be kept anyway). Delete/Backspace = confirm the
exclusion (yes, it really is a duplicate -- it stays out, but now as a
deliberate, recorded human decision rather than a silent automatic one).
Every decision is recorded immediately via
`review_decisions.record_duplicate_review_decision()`; the Final package
is only rebuilt once, when the review session ends, and only if at
least one document was restored -- never once per keystroke, which
would make reviewing more than a couple of documents painfully slow.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ... import review_decisions
from ...config import AppConfig
from ...models import RunResult, SourceOccurrence
from ...pdf_render import render_page_thumbnail_png

_THUMBNAIL_MAX_DIMENSION_PX = 220

_METHOD_LABELS = {
    "exact_sha256": "Byte-for-byte identical",
    "normalized_pdf": "Identical after formatting-only normalization",
    "content_equivalent": "Equivalent text/visual content",
    "blank_page_tolerant": "Equivalent content (ignoring blank pages)",
}


def _thumbnail_label(pdf_path: Path | None) -> QLabel:
    label = QLabel()
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setFixedSize(_THUMBNAIL_MAX_DIMENSION_PX, _THUMBNAIL_MAX_DIMENSION_PX)
    label.setObjectName("Card")
    if pdf_path is None:
        label.setText("(preview unavailable)")
        return label
    try:
        png_bytes = render_page_thumbnail_png(pdf_path, 0, _THUMBNAIL_MAX_DIMENSION_PX)
        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes, "PNG")
        if pixmap.isNull():
            raise ValueError("empty pixmap")
        label.setPixmap(pixmap)
    except Exception:
        label.setText("(preview unavailable)")
    return label


class DuplicateSwipeDialog(QDialog):
    #: Emitted once, when the session ends, if at least one decision was
    #: recorded -- callers use this to know whether ResultView's stats
    #: need refreshing (mirrors UncertainReviewDialog.decisions_applied).
    decisions_applied = Signal()

    def __init__(
        self,
        run: RunResult,
        config: AppConfig,
        allow_large_input: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Review Possible Duplicates")
        self.resize(760, 560)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.run = run
        self.config = config
        self.allow_large_input = allow_large_input
        self.occ_by_id = {o.document_id: o for o in run.occurrences}

        self.candidates: list[SourceOccurrence] = [
            o for o in run.occurrences if o.is_confident_duplicate_candidate
        ]
        self._index = 0
        self._any_decision_recorded = False
        self._restored_count = 0
        self._confirmed_count = 0
        self._tmp_dir: str | None = None

        if self.candidates:
            self._tmp_dir = tempfile.mkdtemp(prefix="lpb_dup_review_")
            to_render = list(self.candidates)
            for occ in self.candidates:
                counterpart_id = occ.content_duplicate_of_document_id or occ.contained_in_document_id
                counterpart = self.occ_by_id.get(counterpart_id) if counterpart_id else None
                if counterpart is not None:
                    to_render.append(counterpart)
            review_decisions.ensure_converted_pdfs_available(run, to_render, Path(self._tmp_dir))

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        self.heading_label = QLabel()
        self.heading_label.setObjectName("SectionHeading")
        layout.addWidget(self.heading_label)

        self.detail_label = QLabel()
        self.detail_label.setObjectName("MutedLabel")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)

        excluded_col = QVBoxLayout()
        excluded_title = QLabel("Excluded automatically")
        excluded_title.setObjectName("MutedLabel")
        excluded_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        excluded_col.addWidget(excluded_title)
        self.excluded_thumbnail_slot = QVBoxLayout()
        excluded_col.addLayout(self.excluded_thumbnail_slot)
        self.excluded_name_label = QLabel()
        self.excluded_name_label.setWordWrap(True)
        self.excluded_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        excluded_col.addWidget(self.excluded_name_label)
        cards_row.addLayout(excluded_col)

        kept_col = QVBoxLayout()
        kept_title = QLabel("Matched against (kept in Final)")
        kept_title.setObjectName("MutedLabel")
        kept_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        kept_col.addWidget(kept_title)
        self.kept_thumbnail_slot = QVBoxLayout()
        kept_col.addLayout(self.kept_thumbnail_slot)
        self.kept_name_label = QLabel()
        self.kept_name_label.setWordWrap(True)
        self.kept_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        kept_col.addWidget(self.kept_name_label)
        cards_row.addLayout(kept_col)

        layout.addLayout(cards_row, stretch=1)

        button_row = QHBoxLayout()
        button_row.setSpacing(12)

        self.confirm_button = QPushButton("Confirm Duplicate -- Exclude  (Delete)")
        self.confirm_button.clicked.connect(self._on_confirm_duplicate)
        button_row.addWidget(self.confirm_button)

        self.keep_button = QPushButton("Keep in Final  (Enter)")
        self.keep_button.setObjectName("PrimaryButton")
        self.keep_button.clicked.connect(self._on_keep)
        button_row.addWidget(self.keep_button)

        layout.addLayout(button_row)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.close_button)

        if self.candidates:
            self._show_card(0)
        else:
            self._show_empty_state()

    # -- card display ----------------------------------------------

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _show_card(self, index: int) -> None:
        occ = self.candidates[index]
        self.heading_label.setText(f"Reviewing {index + 1} of {len(self.candidates)}")

        method = _METHOD_LABELS.get(occ.duplicate_detection_method, occ.duplicate_detection_method or "unknown")
        confidence = f"{occ.duplicate_confidence:.0%}" if occ.duplicate_confidence is not None else "n/a"
        self.detail_label.setText(f"Detection method: {method}  --  confidence: {confidence}")

        self._clear_layout(self.excluded_thumbnail_slot)
        self.excluded_thumbnail_slot.addWidget(_thumbnail_label(occ.converted_pdf_path))
        self.excluded_name_label.setText(f"{occ.original_relative_path}  ({occ.converted_page_count or 0} page(s))")

        counterpart_id = occ.content_duplicate_of_document_id or occ.contained_in_document_id
        counterpart = self.occ_by_id.get(counterpart_id) if counterpart_id else None
        self._clear_layout(self.kept_thumbnail_slot)
        self.kept_thumbnail_slot.addWidget(
            _thumbnail_label(counterpart.converted_pdf_path if counterpart else None)
        )
        if counterpart is not None:
            self.kept_name_label.setText(
                f"{counterpart.original_relative_path}  ({counterpart.converted_page_count or 0} page(s))"
            )
        else:
            self.kept_name_label.setText("(not found)")

        self.confirm_button.setEnabled(True)
        self.keep_button.setEnabled(True)

    def _show_empty_state(self) -> None:
        self.heading_label.setText("Nothing to review")
        self.detail_label.setText(
            "No confident automatic duplicate/containment exclusions were found in this run -- there "
            "is nothing here that needs a second look."
        )
        self.confirm_button.setEnabled(False)
        self.keep_button.setEnabled(False)

    def _show_finished_state(self) -> None:
        self.heading_label.setText("Review complete")
        self.detail_label.setText(
            f"Reviewed {len(self.candidates)} document(s): {self._restored_count} kept in Final, "
            f"{self._confirmed_count} confirmed as duplicates."
        )
        self._clear_layout(self.excluded_thumbnail_slot)
        self._clear_layout(self.kept_thumbnail_slot)
        self.excluded_name_label.setText("")
        self.kept_name_label.setText("")
        self.confirm_button.setEnabled(False)
        self.keep_button.setEnabled(False)

    # -- decisions ----------------------------------------------

    def _on_keep(self) -> None:
        self._record(self.candidates[self._index], "restored")

    def _on_confirm_duplicate(self) -> None:
        self._record(self.candidates[self._index], "confirmed_duplicate")

    def _record(self, occ: SourceOccurrence, decision: str) -> None:
        review_decisions.record_duplicate_review_decision(self.run, occ.document_id, decision)
        self._any_decision_recorded = True
        if decision == "restored":
            self._restored_count += 1
        else:
            self._confirmed_count += 1
        self._index += 1
        if self._index >= len(self.candidates):
            self._finish()
        else:
            self._show_card(self._index)

    def _finish(self) -> None:
        if self._restored_count > 0:
            review_decisions.rebuild_final_and_reports(self.run, self.config, self.allow_large_input)
        self._show_finished_state()
        if self._any_decision_recorded:
            self.decisions_applied.emit()

    # -- keyboard ----------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if self._index < len(self.candidates):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._on_keep()
                return
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self._on_confirm_duplicate()
                return
        super().keyPressEvent(event)

    # -- cleanup ----------------------------------------------

    def done(self, result: int) -> None:  # noqa: N802 - Qt override
        if self._tmp_dir is not None:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None
        super().done(result)
