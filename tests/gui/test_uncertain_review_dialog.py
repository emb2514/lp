from __future__ import annotations

from pathlib import Path

from lender_package_builder.gui.widgets.uncertain_review_dialog import UncertainReviewDialog
from lender_package_builder.models import (
    IntegrityCheckResult,
    OutputPart,
    ProcessingStatus,
    RunResult,
    SourceOccurrence,
)


def _occ(doc_id: str, needs_review: bool = False, review_reason: str | None = None) -> SourceOccurrence:
    return SourceOccurrence(
        document_id=doc_id,
        traversal_index=int(doc_id.split("-")[-1]),
        original_filename=f"{doc_id}.pdf",
        original_relative_path=f"folder/{doc_id}.pdf",
        original_extension=".pdf",
        original_size_bytes=1000,
        status=ProcessingStatus.CONVERTED,
        converted_page_count=3,
        needs_review=needs_review,
        review_reason=review_reason,
    )


def _make_run(tmp_path: Path, occurrences: list[SourceOccurrence]) -> RunResult:
    output_path = tmp_path / "output"
    output_path.mkdir(exist_ok=True)
    doc_ids = [o.document_id for o in occurrences]
    part = OutputPart(
        package="Final", index=1, file_path=output_path / "Final" / "part1.pdf",
        document_ids=doc_ids, page_count=3 * len(doc_ids), file_size_bytes=10000,
    )
    return RunResult(
        input_path=tmp_path / "input.zip",
        output_path=output_path,
        start_time="2026-01-01T00:00:00",
        end_time="2026-01-01T00:01:00",
        elapsed_seconds=10.0,
        occurrences=occurrences,
        og_parts=[part],
        final_parts=[part],
        integrity_checks=[IntegrityCheckResult(name="check", passed=True, detail="ok")],
    )


# TEST - dialog lists every needs_review occurrence with its reason
def test_dialog_lists_flagged_occurrences_with_reasons(qtbot, tmp_path):
    occ_a = _occ("DOC-000001", needs_review=True, review_reason="uncertain content match against DOC-000002")
    occ_b = _occ("DOC-000002", needs_review=True, review_reason="uncertain content match against DOC-000001")
    occ_c = _occ("DOC-000003")  # not flagged

    run = _make_run(tmp_path, [occ_a, occ_b, occ_c])
    dialog = UncertainReviewDialog(run)
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 2
    assert dialog.flagged == [occ_a, occ_b]

    filenames = {dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())}
    assert filenames == {"folder/DOC-000001.pdf", "folder/DOC-000002.pdf"}

    reasons = {dialog.table.item(row, 2).text() for row in range(dialog.table.rowCount())}
    assert "uncertain content match against DOC-000002" in reasons
    assert "uncertain content match against DOC-000001" in reasons
    assert "2 document(s)" in dialog.heading_label.text()
    dialog.close()


# TEST - dialog shows a clean empty state when nothing was flagged
def test_dialog_shows_empty_state_when_nothing_flagged(qtbot, tmp_path):
    occ = _occ("DOC-000001")
    run = _make_run(tmp_path, [occ])
    dialog = UncertainReviewDialog(run)
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 0
    assert dialog.flagged == []
    assert "No uncertain matches" in dialog.heading_label.text()
    dialog.close()


# TEST - never an approval workflow: the table is read-only, no editing/selection controls
def test_dialog_table_is_read_only(qtbot, tmp_path):
    occ = _occ("DOC-000001", needs_review=True, review_reason="uncertain match")
    run = _make_run(tmp_path, [occ])
    dialog = UncertainReviewDialog(run)
    qtbot.addWidget(dialog)

    from PySide6.QtWidgets import QAbstractItemView

    assert dialog.table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    dialog.close()


# TEST - the review button on ResultView opens the dialog and reflects the run's flagged occurrences
def test_result_view_review_button_opens_dialog(window, tmp_path, monkeypatch):
    occ_a = _occ("DOC-000001", needs_review=True, review_reason="uncertain overlap match")
    occ_b = _occ("DOC-000002")
    run = _make_run(tmp_path, [occ_a, occ_b])

    window._on_build_finished(run)
    assert window.stack.currentWidget() is window.result_view

    opened = {}

    class _FakeDialog:
        def __init__(self, run_arg, parent=None):
            opened["run"] = run_arg

        def exec(self):
            opened["exec_called"] = True

    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.result_view.UncertainReviewDialog", _FakeDialog
    )
    window.result_view.review_uncertain_button.click()

    assert opened["exec_called"] is True
    assert opened["run"] is run
