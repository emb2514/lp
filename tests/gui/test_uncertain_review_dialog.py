"""Tests for the interactive "Review Uncertain Matches" dialog: default
Keep Both behavior, explicit exclude decisions, the required
confirmation step, cancellation (both at the dialog level and at the
confirmation-popup level), persistence of decisions within a session,
and that decisions correctly rebuild Final while leaving OG and the
original source files untouched.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from fixtures import builders
from lender_package_builder import merging
from lender_package_builder.config import AppConfig
from lender_package_builder.gui.widgets.uncertain_review_dialog import UncertainReviewDialog
from lender_package_builder.models import (
    IntegrityCheckResult,
    ProcessingStatus,
    RunResult,
    SourceOccurrence,
    UncertainMatch,
)


def _occ(doc_id: str, pdf_path: Path, pages: int = 2, needs_review: bool = True) -> SourceOccurrence:
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
        needs_review=needs_review,
    )


def _make_run(tmp_path: Path, config: AppConfig, kind: str = "content_duplicate") -> RunResult:
    output_path = tmp_path / "output"
    (output_path / "Final").mkdir(parents=True, exist_ok=True)
    (output_path / "OG").mkdir(parents=True, exist_ok=True)
    (output_path / "Reports").mkdir(parents=True, exist_ok=True)

    a_pdf = builders.make_pdf(tmp_path / "D1.pdf", pages=2, text_prefix="A")
    b_pdf = builders.make_pdf(tmp_path / "D2.pdf", pages=2, text_prefix="B")
    occ_a = _occ("D1", a_pdf)
    occ_b = _occ("D2", b_pdf)

    final_parts = merging.write_package(
        [occ_a, occ_b], output_path / "Final", "Full_Lender_Package_Final_Part", "Final",
        config.max_pages_per_part, config.max_size_bytes_per_part,
    )
    og_parts = merging.write_package(
        [occ_a, occ_b], output_path / "OG", "Full_Lender_Package_OG_Files_Part", "OG",
        config.max_pages_per_part, config.max_size_bytes_per_part,
    )

    excludable = ("D1", "D2") if kind == "content_duplicate" else ("D1",)
    match = UncertainMatch(
        match_id="UM-0001", kind=kind, document_id_a="D1", document_id_b="D2",
        confidence=0.85, detail="uncertain match for testing", excludable_ids=excludable,
    )

    return RunResult(
        input_path=tmp_path, output_path=output_path, start_time="t",
        occurrences=[occ_a, occ_b], og_parts=og_parts, final_parts=final_parts,
        integrity_checks=[IntegrityCheckResult("x", True, "ok")],
        uncertain_matches=[match],
    )


# TEST - Keep Both is selected by default
def test_keep_both_is_default_selection(qtbot, tmp_path):
    config = AppConfig()
    run = _make_run(tmp_path, config)
    dialog = UncertainReviewDialog(run, config)
    qtbot.addWidget(dialog)

    assert dialog.selected_action("UM-0001") == "keep_both"
    controls = dialog._controls["UM-0001"]
    assert controls["keep_both"].isChecked() is True
    for radio in controls["exclude"].values():
        assert radio.isChecked() is False
    dialog.close()


# TEST - applying with the default selection records keep_both and changes no files
def test_applying_default_keep_both_changes_nothing_on_disk(qtbot, tmp_path):
    config = AppConfig()
    run = _make_run(tmp_path, config)
    dialog = UncertainReviewDialog(run, config)
    qtbot.addWidget(dialog)

    final_before = {doc_id for p in run.final_parts for doc_id in p.document_ids}

    dialog.apply_button.click()

    final_after = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert final_before == final_after == {"D1", "D2"}
    match = run.uncertain_matches[0]
    assert match.decision == "keep_both"
    assert match.decided_at is not None
    dialog.close()


# TEST - explicit exclude decision, after confirming, removes exactly the chosen document from Final
def test_explicit_exclude_decision_removes_chosen_document(qtbot, tmp_path, monkeypatch):
    config = AppConfig()
    run = _make_run(tmp_path, config)
    dialog = UncertainReviewDialog(run, config)
    qtbot.addWidget(dialog)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    controls = dialog._controls["UM-0001"]
    controls["exclude"]["D2"].setChecked(True)
    assert dialog.selected_action("UM-0001") == "D2"

    applied_signal = []
    dialog.decisions_applied.connect(lambda: applied_signal.append(True))
    dialog.apply_button.click()

    assert applied_signal == [True]
    match = run.uncertain_matches[0]
    assert match.decision == "excluded"
    assert match.decided_document_id == "D2"

    final_ids = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert final_ids == {"D1"}

    og_ids = {doc_id for p in run.og_parts for doc_id in p.document_ids}
    assert og_ids == {"D1", "D2"}, "OG must always retain both regardless of the review decision"

    occ_d2 = next(o for o in run.occurrences if o.document_id == "D2")
    assert occ_d2.manually_excluded is True
    assert occ_d2.manually_excluded_match_id == "UM-0001"

    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"
    dialog.close()


# TEST - the merged_containment kind only offers the standalone side as excludable
def test_containment_match_only_offers_standalone_as_excludable(qtbot, tmp_path):
    config = AppConfig()
    run = _make_run(tmp_path, config, kind="merged_containment")
    dialog = UncertainReviewDialog(run, config)
    qtbot.addWidget(dialog)

    controls = dialog._controls["UM-0001"]
    assert set(controls["exclude"].keys()) == {"D1"}
    dialog.close()


# TEST - cancelling the confirmation popup applies nothing
def test_cancelling_confirmation_popup_applies_nothing(qtbot, tmp_path, monkeypatch):
    config = AppConfig()
    run = _make_run(tmp_path, config)
    dialog = UncertainReviewDialog(run, config)
    qtbot.addWidget(dialog)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

    controls = dialog._controls["UM-0001"]
    controls["exclude"]["D2"].setChecked(True)

    final_before = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    dialog.apply_button.click()
    final_after = {doc_id for p in run.final_parts for doc_id in p.document_ids}

    assert final_before == final_after == {"D1", "D2"}
    assert run.uncertain_matches[0].decision == "undecided"
    dialog.close()


# TEST - closing/cancelling the dialog without clicking Apply changes nothing
def test_closing_dialog_without_applying_changes_nothing(qtbot, tmp_path):
    config = AppConfig()
    run = _make_run(tmp_path, config)
    dialog = UncertainReviewDialog(run, config)
    qtbot.addWidget(dialog)

    controls = dialog._controls["UM-0001"]
    controls["exclude"]["D2"].setChecked(True)  # selected but never applied

    dialog.cancel_button.click()

    assert run.uncertain_matches[0].decision == "undecided"
    final_ids = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert final_ids == {"D1", "D2"}


# TEST - a decision persists within the session: reopening the dialog on
# the same run shows the match as already decided, read-only
def test_decision_persists_across_dialog_reopen(qtbot, tmp_path, monkeypatch):
    config = AppConfig()
    run = _make_run(tmp_path, config)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    dialog1 = UncertainReviewDialog(run, config)
    qtbot.addWidget(dialog1)
    dialog1._controls["UM-0001"]["exclude"]["D2"].setChecked(True)
    dialog1.apply_button.click()
    dialog1.close()

    dialog2 = UncertainReviewDialog(run, config)
    qtbot.addWidget(dialog2)
    assert "UM-0001" not in dialog2._controls  # no longer interactive -- already decided
    assert dialog2.apply_button.isEnabled() is False
    dialog2.close()


# TEST - the audit trail (Uncertain_Match_Review_Log.txt) records the decision
def test_exclusion_decision_is_recorded_in_audit_report(qtbot, tmp_path, monkeypatch):
    config = AppConfig()
    run = _make_run(tmp_path, config)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    dialog = UncertainReviewDialog(run, config)
    qtbot.addWidget(dialog)
    dialog._controls["UM-0001"]["exclude"]["D2"].setChecked(True)
    dialog.apply_button.click()
    dialog.close()

    log_text = (run.output_path / "Reports" / "Uncertain_Match_Review_Log.txt").read_text()
    assert "EXCLUDED" in log_text
    assert "D2.pdf" in log_text
    assert "Reviewed and decided: 1" in log_text

    manifest_text = (run.output_path / "Reports" / "Processing_Manifest.json").read_text()
    assert "uncertain_matches" in manifest_text
    assert "excluded" in manifest_text


# TEST - the empty state is shown cleanly when there are no uncertain matches
def test_dialog_shows_empty_state_when_no_uncertain_matches(qtbot, tmp_path):
    config = AppConfig()
    run = _make_run(tmp_path, config)
    run.uncertain_matches = []
    dialog = UncertainReviewDialog(run, config)
    qtbot.addWidget(dialog)

    assert "No uncertain matches were found" in dialog.heading_label.text()
    assert dialog.apply_button.isEnabled() is False
    dialog.close()


# TEST - ResultView's review button opens the dialog with the run's stored config
def test_result_view_review_button_opens_dialog_with_config(window, tmp_path, monkeypatch):
    config = AppConfig()
    run = _make_run(tmp_path, config)

    window.result_view.set_result(run, False, config, False)

    opened = {}

    class _FakeDialog:
        def __init__(self, run_arg, config_arg, allow_large_input_arg, parent=None):
            opened["run"] = run_arg
            opened["config"] = config_arg

        def exec(self):
            opened["exec_called"] = True

        @property
        def decisions_applied(self):
            class _Signal:
                def connect(self, *_a, **_k):
                    pass
            return _Signal()

    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.result_view.UncertainReviewDialog", _FakeDialog
    )
    window.result_view.review_uncertain_button.click()

    assert opened["exec_called"] is True
    assert opened["run"] is run
    assert opened["config"] is config
