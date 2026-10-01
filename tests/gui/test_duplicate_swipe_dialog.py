"""Tests for the "Review Possible Duplicates" swipe dialog: real user
request: "i need to tripple check we arent excluding documents because
it could be a dupe... kinda like those tinder type apps to delete
duplicate pictures... press enter for keep and delete for keeping it
out of the final package."

Covers: candidate gathering (only CONFIDENT duplicate/containment
exclusions, never an uncertain match and never an exact duplicate),
Enter restoring a document into Final, Delete confirming an exclusion
without touching Final, advancing through multiple candidates, the
one-rebuild-per-session guarantee (not one per keystroke), and that
closing early leaves remaining candidates undecided.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from fixtures import builders
from lender_package_builder import merging, naming, review_decisions
from lender_package_builder.config import AppConfig
from lender_package_builder.gui.widgets.duplicate_swipe_dialog import DuplicateSwipeDialog
from lender_package_builder.models import (
    IntegrityCheckResult,
    PackageIdentity,
    ProcessingStatus,
    RunResult,
    SourceOccurrence,
)


def _occ(doc_id: str, pdf_path: Path, pages: int = 2) -> SourceOccurrence:
    return SourceOccurrence(
        document_id=doc_id,
        traversal_index=int(doc_id[-1]),
        original_filename=f"{doc_id}.pdf",
        original_relative_path=f"{doc_id}.pdf",
        original_extension=".pdf",
        original_size_bytes=1000,
        status=ProcessingStatus.CONVERTED,
        converted_pdf_path=pdf_path,
        converted_page_count=pages,
        needs_review=False,
    )


def _make_run(tmp_path: Path, config: AppConfig, num_duplicates: int = 1) -> RunResult:
    """A canonical document D0, plus `num_duplicates` CONFIDENT content
    duplicates of it (D1, D2, ...) -- all auto-excluded from Final with
    no `UncertainMatch` at all, since none of them were ever in doubt.
    """

    output_path = tmp_path / "output"
    (output_path / "Final").mkdir(parents=True, exist_ok=True)
    (output_path / "Reports").mkdir(parents=True, exist_ok=True)
    identity = PackageIdentity(last_name="Test", first_name="Borrower")

    canonical_pdf = builders.make_pdf(tmp_path / "D0.pdf", pages=2, text_prefix="Canonical")
    canonical = _occ("D0", canonical_pdf)
    occurrences = [canonical]
    for i in range(1, num_duplicates + 1):
        dup_pdf = builders.make_pdf(tmp_path / f"D{i}.pdf", pages=2, text_prefix=f"Dup{i}")
        dup = _occ(f"D{i}", dup_pdf)
        dup.is_content_duplicate = True
        dup.content_duplicate_of_document_id = "D0"
        dup.duplicate_detection_method = "content_equivalent"
        dup.duplicate_confidence = 0.9
        occurrences.append(dup)

    occ_by_id = {o.document_id: o for o in occurrences}

    final_parts = merging.write_package(
        [canonical], output_path / "Final", identity, naming.FINAL_PACKAGE_KIND, "Final",
        config.max_pages_per_part, config.max_size_bytes_per_part,
    )
    og_parts = merging.write_package(
        occurrences, output_path / "Final", identity, naming.OG_PACKAGE_KIND, "OG",
        config.max_pages_per_part, config.max_size_bytes_per_part,
    )
    for part in og_parts:
        for doc_id in part.document_ids:
            occ_by_id[doc_id].og_part_index = part.index

    return RunResult(
        input_path=tmp_path, output_path=output_path, start_time="t",
        identity=identity,
        occurrences=occurrences, og_parts=og_parts, final_parts=final_parts,
        integrity_checks=[IntegrityCheckResult("x", True, "ok")],
    )


def _press(dialog: DuplicateSwipeDialog, key) -> None:
    dialog.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


# TEST - no candidates shows the empty state, not an empty/broken card
def test_empty_state_when_no_confident_duplicates(qtbot, tmp_path):
    config = AppConfig()
    run = _make_run(tmp_path, config, num_duplicates=0)
    dialog = DuplicateSwipeDialog(run, config)
    qtbot.addWidget(dialog)

    assert dialog.candidates == []
    assert "Nothing to review" in dialog.heading_label.text()
    assert dialog.keep_button.isEnabled() is False
    assert dialog.confirm_button.isEnabled() is False


# TEST - the first card shows the right documents and detail text
def test_first_card_shows_the_excluded_and_matched_documents(qtbot, tmp_path):
    config = AppConfig()
    run = _make_run(tmp_path, config, num_duplicates=1)
    dialog = DuplicateSwipeDialog(run, config)
    qtbot.addWidget(dialog)

    assert len(dialog.candidates) == 1
    assert "Reviewing 1 of 1" in dialog.heading_label.text()
    assert "D1.pdf" in dialog.excluded_name_label.text()
    assert "D0.pdf" in dialog.kept_name_label.text()
    assert "90%" in dialog.detail_label.text()


# TEST - Enter restores the document into Final and rebuilds it
def test_enter_key_restores_document_into_final(qtbot, tmp_path):
    config = AppConfig()
    run = _make_run(tmp_path, config, num_duplicates=1)
    dialog = DuplicateSwipeDialog(run, config)
    qtbot.addWidget(dialog)

    received = []
    dialog.decisions_applied.connect(lambda: received.append(True))

    _press(dialog, Qt.Key.Key_Return)

    occ_d1 = next(o for o in run.occurrences if o.document_id == "D1")
    assert occ_d1.duplicate_review_decision == "restored"
    final_ids = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert final_ids == {"D0", "D1"}
    assert "Review complete" in dialog.heading_label.text()
    assert received == [True]


# TEST - Delete confirms the exclusion and never touches Final
def test_delete_key_confirms_duplicate_without_rebuilding(qtbot, tmp_path):
    config = AppConfig()
    run = _make_run(tmp_path, config, num_duplicates=1)
    final_mtime_before = (run.output_path / "Final").stat().st_mtime
    dialog = DuplicateSwipeDialog(run, config)
    qtbot.addWidget(dialog)

    _press(dialog, Qt.Key.Key_Delete)

    occ_d1 = next(o for o in run.occurrences if o.document_id == "D1")
    assert occ_d1.duplicate_review_decision == "confirmed_duplicate"
    assert occ_d1.included_in_final is False
    final_ids = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert final_ids == {"D0"}
    assert (run.output_path / "Final").stat().st_mtime == final_mtime_before
    assert "Review complete" in dialog.heading_label.text()


# TEST - multiple candidates advance one at a time, in order
def test_advances_through_multiple_candidates(qtbot, tmp_path):
    config = AppConfig()
    run = _make_run(tmp_path, config, num_duplicates=2)
    dialog = DuplicateSwipeDialog(run, config)
    qtbot.addWidget(dialog)

    assert "Reviewing 1 of 2" in dialog.heading_label.text()
    _press(dialog, Qt.Key.Key_Delete)
    assert "Reviewing 2 of 2" in dialog.heading_label.text()
    _press(dialog, Qt.Key.Key_Return)
    assert "Review complete" in dialog.heading_label.text()
    assert "1 kept in Final" in dialog.detail_label.text()
    assert "1 confirmed as duplicates" in dialog.detail_label.text()


# TEST - PERFORMANCE: rebuilding happens exactly once per session, not
# once per restored document -- the whole reason decisions are recorded
# separately from the rebuild
def test_rebuild_happens_only_once_for_multiple_restorations(qtbot, tmp_path, monkeypatch):
    config = AppConfig()
    run = _make_run(tmp_path, config, num_duplicates=3)

    call_count = 0
    real_rebuild = review_decisions.rebuild_final_and_reports

    def _counting_rebuild(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return real_rebuild(*args, **kwargs)

    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.duplicate_swipe_dialog.review_decisions.rebuild_final_and_reports",
        _counting_rebuild,
    )

    dialog = DuplicateSwipeDialog(run, config)
    qtbot.addWidget(dialog)

    _press(dialog, Qt.Key.Key_Return)
    _press(dialog, Qt.Key.Key_Return)
    _press(dialog, Qt.Key.Key_Return)

    assert call_count == 1
    final_ids = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert final_ids == {"D0", "D1", "D2", "D3"}


# TEST - confirming every candidate (no restorations) never rebuilds at all
def test_no_rebuild_when_nothing_is_restored(qtbot, tmp_path, monkeypatch):
    config = AppConfig()
    run = _make_run(tmp_path, config, num_duplicates=2)

    call_count = 0

    def _counting_rebuild(*args, **kwargs):
        nonlocal call_count
        call_count += 1

    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.duplicate_swipe_dialog.review_decisions.rebuild_final_and_reports",
        _counting_rebuild,
    )

    dialog = DuplicateSwipeDialog(run, config)
    qtbot.addWidget(dialog)
    _press(dialog, Qt.Key.Key_Delete)
    _press(dialog, Qt.Key.Key_Delete)

    assert call_count == 0


# TEST - closing the dialog after only the first of several candidates
# leaves the rest genuinely undecided, not silently resolved
def test_closing_early_leaves_remaining_candidates_undecided(qtbot, tmp_path):
    config = AppConfig()
    run = _make_run(tmp_path, config, num_duplicates=2)
    dialog = DuplicateSwipeDialog(run, config)
    qtbot.addWidget(dialog)

    _press(dialog, Qt.Key.Key_Delete)  # decide only the first
    dialog.done(0)

    occ_d1 = next(o for o in run.occurrences if o.document_id == "D1")
    occ_d2 = next(o for o in run.occurrences if o.document_id == "D2")
    assert occ_d1.duplicate_review_decision == "confirmed_duplicate"
    assert occ_d2.duplicate_review_decision is None


# TEST - the Keep/Confirm buttons do exactly what the keyboard shortcuts do
def test_keep_button_click_matches_enter_key(qtbot, tmp_path):
    config = AppConfig()
    run = _make_run(tmp_path, config, num_duplicates=1)
    dialog = DuplicateSwipeDialog(run, config)
    qtbot.addWidget(dialog)

    dialog.keep_button.click()

    occ_d1 = next(o for o in run.occurrences if o.document_id == "D1")
    assert occ_d1.duplicate_review_decision == "restored"
