"""Interactive review screen for every occurrence RC2's content-aware
analysis could not decide automatically (`needs_review=True`).

Every uncertain match starts on, and defaults to, "Keep Both" -- the
only automatically-taken action anywhere in this app. Both documents
stay in the Final package unless a human explicitly selects a specific
document to exclude AND confirms that choice in a separate, blocking
confirmation step. Nothing is ever excluded silently, automatically, or
without an intentional, recorded decision.

Applying a decision calls `review_decisions.apply_review_decision()`,
which is the ONLY place in the whole application allowed to exclude a
`needs_review=True` occurrence from Final -- it records the decision
(who/what/when/why) on the matching `UncertainMatch`, rebuilds ONLY the
Final package (never OG, never any original source file), reruns every
integrity check, and rewrites every report so the on-disk audit trail
(`Uncertain_Match_Review_Log.txt` and the other reports) always
reflects the complete, current set of decisions.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ... import review_decisions
from ...config import AppConfig
from ...models import RunResult, SourceOccurrence, UncertainMatch

_KIND_LABELS = {
    "content_duplicate": "Possible content duplicate",
    "merged_containment": "Possible merged-package containment",
}


def _describe_occurrence(occ: SourceOccurrence | None, document_id: str) -> str:
    if occ is None:
        return document_id
    detail = f"{occ.original_relative_path}  ({occ.converted_page_count or 0} page(s))"
    if occ.version_classification:
        detail += f"  [{occ.version_classification}]"
    return detail


class UncertainReviewDialog(QDialog):
    #: Emitted once, after Apply successfully records at least one
    #: decision (keep-both or exclude) -- callers use this to know
    #: whether ResultView's stats/Final counts need refreshing.
    decisions_applied = Signal()

    def __init__(
        self,
        run: RunResult,
        config: AppConfig,
        allow_large_input: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Review Uncertain Matches")
        self.resize(760, 520)

        self.run = run
        self.config = config
        self.allow_large_input = allow_large_input
        self.occ_by_id = {o.document_id: o for o in run.occurrences}

        # match_id -> {"group": QButtonGroup, "keep_both": QRadioButton,
        # "exclude": {document_id: QRadioButton}}
        self._controls: dict[str, dict] = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.heading_label = QLabel()
        self.heading_label.setObjectName("MutedLabel")
        self.heading_label.setWordWrap(True)
        layout.addWidget(self.heading_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        layout.addWidget(self.scroll_area, stretch=1)

        button_box = QDialogButtonBox()
        self.apply_button = button_box.addButton("Apply Decisions", QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_button = button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self.apply_button.clicked.connect(self._on_apply_clicked)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(button_box)

        self._rebuild()

    # -- construction ----------------------------------------------

    def _rebuild(self) -> None:
        matches = self.run.uncertain_matches
        undecided = [m for m in matches if m.decision == "undecided"]

        if not matches:
            self.heading_label.setText(
                "No uncertain matches were found in this run. Every duplicate/containment decision "
                "the engine made met its safe confidence threshold."
            )
        else:
            self.heading_label.setText(
                f"{len(matches)} comparison(s) could not be confirmed automatically. \"Keep Both\" is "
                "selected by default and is always safe -- nothing is excluded unless you explicitly "
                "choose a document below and click Apply Decisions, which asks you to confirm before "
                "making any change. Both original files always remain untouched, and OG always keeps "
                "everything regardless of what you decide here."
            )

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(10)

        self._controls.clear()
        for match in matches:
            content_layout.addWidget(self._build_match_card(match))
        content_layout.addStretch(1)

        self.scroll_area.setWidget(content)
        self.apply_button.setEnabled(bool(undecided))

    def _build_match_card(self, match: UncertainMatch) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(6)

        title = QLabel(f"{_KIND_LABELS.get(match.kind, match.kind)}  --  confidence {match.confidence:.2f}")
        title.setObjectName("SectionHeading")
        card_layout.addWidget(title)

        occ_a = self.occ_by_id.get(match.document_id_a)
        occ_b = self.occ_by_id.get(match.document_id_b)
        doc_a_label = QLabel(f"Document A: {_describe_occurrence(occ_a, match.document_id_a)}")
        doc_a_label.setWordWrap(True)
        card_layout.addWidget(doc_a_label)
        doc_b_label = QLabel(f"Document B: {_describe_occurrence(occ_b, match.document_id_b)}")
        doc_b_label.setWordWrap(True)
        card_layout.addWidget(doc_b_label)

        detail_label = QLabel(match.detail)
        detail_label.setObjectName("MutedLabel")
        detail_label.setWordWrap(True)
        card_layout.addWidget(detail_label)

        if match.decision == "undecided":
            group = QButtonGroup(card)
            keep_both = QRadioButton("Keep Both (recommended -- default, always safe)")
            keep_both.setChecked(True)
            group.addButton(keep_both)
            card_layout.addWidget(keep_both)

            exclude_radios: dict[str, QRadioButton] = {}
            for doc_id in match.excludable_ids:
                occ = self.occ_by_id.get(doc_id)
                name = occ.original_filename if occ else doc_id
                radio = QRadioButton(f"Mark as duplicate to exclude: {name}")
                group.addButton(radio)
                card_layout.addWidget(radio)
                exclude_radios[doc_id] = radio

            self._controls[match.match_id] = {
                "group": group,
                "keep_both": keep_both,
                "exclude": exclude_radios,
            }
        else:
            status_label = QLabel(self._decision_summary(match))
            status_label.setObjectName("MutedLabel")
            status_label.setWordWrap(True)
            card_layout.addWidget(status_label)

        return card

    def _decision_summary(self, match: UncertainMatch) -> str:
        if match.decision == "keep_both":
            return f"Decision: Kept both -- reviewed {match.decided_at}. {match.decided_reason or ''}"
        excluded_occ = self.occ_by_id.get(match.decided_document_id or "")
        name = excluded_occ.original_filename if excluded_occ else match.decided_document_id
        return f"Decision: Excluded {name} -- reviewed {match.decided_at}. {match.decided_reason or ''}"

    # -- decision gathering / apply ----------------------------------------------

    def selected_action(self, match_id: str) -> str | None:
        """Returns "keep_both", or the document_id chosen for exclusion,
        for a currently-undecided match's radio selection. Returns None
        if the match is not in the undecided set (e.g. already decided).
        """

        controls = self._controls.get(match_id)
        if controls is None:
            return None
        if controls["keep_both"].isChecked():
            return "keep_both"
        for doc_id, radio in controls["exclude"].items():
            if radio.isChecked():
                return doc_id
        return None

    def _on_apply_clicked(self) -> None:
        pending: list[tuple[UncertainMatch, str]] = []
        for match in self.run.uncertain_matches:
            if match.decision != "undecided":
                continue
            action = self.selected_action(match.match_id)
            if action is not None:
                pending.append((match, action))

        exclusions = [(match, action) for match, action in pending if action != "keep_both"]
        if exclusions:
            names = ", ".join(
                (self.occ_by_id[doc_id].original_filename if doc_id in self.occ_by_id else doc_id)
                for _, doc_id in exclusions
            )
            confirmed = QMessageBox.question(
                self,
                "Confirm exclusion",
                f"This will exclude {len(exclusions)} document(s) from the Final package:\n\n{names}\n\n"
                "The Final package will be rebuilt. Original source files and the OG package are never "
                "changed, and this decision is recorded in the audit reports. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirmed != QMessageBox.StandardButton.Yes:
                return  # cancelled -- nothing applied, nothing changes

        applied_any = False
        for match, action in pending:
            if action == "keep_both":
                review_decisions.apply_review_decision(
                    self.run, self.config, match.match_id, "keep_both",
                    allow_large_input=self.allow_large_input,
                )
            else:
                review_decisions.apply_review_decision(
                    self.run, self.config, match.match_id, "excluded",
                    excluded_document_id=action, allow_large_input=self.allow_large_input,
                )
            applied_any = True

        if applied_any:
            self._rebuild()
            self.decisions_applied.emit()
