"""Tests for review_decisions.py -- the engine module applying a human's
explicit review decision from the GUI's "Review Uncertain Matches"
dialog. Covers: default keep-both persistence, explicit exclusion
mutating exactly the chosen document, rejection of invalid requests
(unknown match, already-decided match, invalid exclusion target), OG
and original-source invariance, and integrity/report consistency after
a decision is applied.
"""

from __future__ import annotations

from pathlib import Path

from fixtures.builders import make_pdf

from lender_package_builder import content_dedup, merging, naming, review_decisions
from lender_package_builder.config import AppConfig
from lender_package_builder.models import (
    IntegrityCheckResult,
    PackageIdentity,
    ProcessingStatus,
    RunResult,
    SourceOccurrence,
    UncertainMatch,
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
        needs_review=True,
    )


def _build_run(tmp_path: Path, config: AppConfig, kind: str = "content_duplicate") -> RunResult:
    output_path = tmp_path / "output"
    (output_path / "Final").mkdir(parents=True)
    (output_path / "Reports").mkdir(parents=True)

    identity = PackageIdentity(last_name="Test", first_name="Borrower")

    a_pdf = make_pdf(tmp_path / "D1.pdf", pages=2, text_prefix="A")
    b_pdf = make_pdf(tmp_path / "D2.pdf", pages=2, text_prefix="B")
    occ_a, occ_b = _occ("D1", a_pdf), _occ("D2", b_pdf)

    final_parts = merging.write_package(
        [occ_a, occ_b], output_path / "Final", identity, naming.FINAL_PACKAGE_KIND, "Final",
        config.max_pages_per_part, config.max_size_bytes_per_part,
    )
    og_parts = merging.write_package(
        [occ_a, occ_b], output_path / "Final", identity, naming.OG_PACKAGE_KIND, "OG",
        config.max_pages_per_part, config.max_size_bytes_per_part,
    )
    for part in og_parts:
        for doc_id in part.document_ids:
            {"D1": occ_a, "D2": occ_b}[doc_id].og_part_index = part.index

    excludable = ("D1", "D2") if kind == "content_duplicate" else ("D1",)
    match = UncertainMatch(
        match_id="UM-0001", kind=kind, document_id_a="D1", document_id_b="D2",
        confidence=0.85, detail="uncertain for test", excludable_ids=excludable,
    )

    return RunResult(
        input_path=tmp_path, output_path=output_path, start_time="t",
        identity=identity,
        occurrences=[occ_a, occ_b], og_parts=og_parts, final_parts=final_parts,
        integrity_checks=[IntegrityCheckResult("x", True, "ok")],
        uncertain_matches=[match],
    )


# TEST 1 - keep_both changes no output file, only records the decision
def test_keep_both_changes_no_output_file(tmp_path):
    config = AppConfig()
    run = _build_run(tmp_path, config)
    final_before = {(p.file_path.name, tuple(p.document_ids)) for p in run.final_parts}
    final_mtime_before = (run.output_path / "Final").stat().st_mtime

    review_decisions.apply_review_decision(run, config, "UM-0001", "keep_both", reason="looked fine")

    match = run.uncertain_matches[0]
    assert match.decision == "keep_both"
    assert match.decided_reason == "looked fine"
    assert match.decided_at is not None
    final_after = {(p.file_path.name, tuple(p.document_ids)) for p in run.final_parts}
    assert final_before == final_after


# TEST 2 - explicit exclusion removes exactly the chosen document from Final
def test_explicit_exclusion_removes_only_chosen_document(tmp_path):
    config = AppConfig()
    run = _build_run(tmp_path, config)

    review_decisions.apply_review_decision(
        run, config, "UM-0001", "excluded", excluded_document_id="D2", reason="redundant copy"
    )

    final_ids = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert final_ids == {"D1"}

    occ_d1 = next(o for o in run.occurrences if o.document_id == "D1")
    occ_d2 = next(o for o in run.occurrences if o.document_id == "D2")
    assert occ_d1.manually_excluded is False
    assert occ_d2.manually_excluded is True
    assert occ_d2.manually_excluded_match_id == "UM-0001"


# TEST 3 - OG and every original source file are untouched by an exclusion
def test_og_and_original_files_untouched_by_exclusion(tmp_path):
    config = AppConfig()
    run = _build_run(tmp_path, config)
    og_before = {doc_id for p in run.og_parts for doc_id in p.document_ids}
    og_part_mtimes_before = {p.file_path: p.file_path.stat().st_mtime for p in run.og_parts}
    original_bytes_before = {
        o.document_id: o.converted_pdf_path.read_bytes() for o in run.occurrences
    }

    review_decisions.apply_review_decision(run, config, "UM-0001", "excluded", excluded_document_id="D2")

    og_after = {doc_id for p in run.og_parts for doc_id in p.document_ids}
    assert og_before == og_after == {"D1", "D2"}
    for path, mtime in og_part_mtimes_before.items():
        assert path.stat().st_mtime == mtime, "OG output file must not be rewritten"
    for o in run.occurrences:
        assert o.converted_pdf_path.read_bytes() == original_bytes_before[o.document_id]


# TEST 4 - integrity checks pass after an exclusion, including the new
# manual-decision-specific checks
def test_integrity_checks_pass_after_exclusion(tmp_path):
    config = AppConfig()
    run = _build_run(tmp_path, config)

    review_decisions.apply_review_decision(run, config, "UM-0001", "excluded", excluded_document_id="D2")

    assert run.success is True
    check_names = {c.name for c in run.integrity_checks}
    assert "Manual exclusions trace back to a valid, auditable review decision" in check_names
    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"


# TEST 5 - reports are rewritten with the decision recorded
def test_reports_rewritten_with_decision(tmp_path):
    config = AppConfig()
    run = _build_run(tmp_path, config)

    review_decisions.apply_review_decision(
        run, config, "UM-0001", "excluded", excluded_document_id="D2", reason="explicit test reason"
    )

    log_text = (run.output_path / "Reports" / "Uncertain_Match_Review_Log.txt").read_text()
    assert "explicit test reason" in log_text
    assert "D2.pdf" in log_text
    assert "EXCLUDED" in log_text

    manifest_text = (run.output_path / "Reports" / "Processing_Manifest.json").read_text()
    assert '"decision": "excluded"' in manifest_text
    assert '"decided_document_id": "D2"' in manifest_text


# TEST 6 - re-deciding an already-decided match raises and changes nothing
def test_redeciding_an_already_decided_match_raises(tmp_path):
    config = AppConfig()
    run = _build_run(tmp_path, config)
    review_decisions.apply_review_decision(run, config, "UM-0001", "keep_both")

    final_before = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    try:
        review_decisions.apply_review_decision(run, config, "UM-0001", "excluded", excluded_document_id="D2")
        assert False, "expected ReviewDecisionError"
    except review_decisions.ReviewDecisionError:
        pass
    final_after = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert final_before == final_after


# TEST 7 - excluding a document not in excludable_ids raises (e.g. the
# merged-package container, which is never a valid exclusion target)
def test_excluding_non_excludable_document_raises(tmp_path):
    config = AppConfig()
    run = _build_run(tmp_path, config, kind="merged_containment")

    try:
        review_decisions.apply_review_decision(run, config, "UM-0001", "excluded", excluded_document_id="D2")
        assert False, "expected ReviewDecisionError"
    except review_decisions.ReviewDecisionError as exc:
        assert "D2" in str(exc)

    final_ids = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert final_ids == {"D1", "D2"}, "nothing should have changed"


# TEST 8 - an unknown match_id raises
def test_unknown_match_id_raises(tmp_path):
    config = AppConfig()
    run = _build_run(tmp_path, config)
    try:
        review_decisions.apply_review_decision(run, config, "UM-9999", "keep_both")
        assert False, "expected ReviewDecisionError"
    except review_decisions.ReviewDecisionError:
        pass


# TEST 9 - an unrecognized decision value raises
def test_unknown_decision_value_raises(tmp_path):
    config = AppConfig()
    run = _build_run(tmp_path, config)
    try:
        review_decisions.apply_review_decision(run, config, "UM-0001", "delete_forever")
        assert False, "expected ReviewDecisionError"
    except review_decisions.ReviewDecisionError:
        pass


# TEST 10 - stale Final part files from before the decision do not linger
def test_stale_final_parts_are_removed_on_rebuild(tmp_path):
    config = AppConfig()
    run = _build_run(tmp_path, config)
    final_dir = run.output_path / "Final"
    files_before = set(final_dir.glob("*.pdf"))
    assert files_before  # sanity: the initial build wrote at least one file

    review_decisions.apply_review_decision(run, config, "UM-0001", "excluded", excluded_document_id="D2")

    files_after = set(final_dir.glob("*.pdf"))
    # Every file currently in the shared Final/Original folder must
    # correspond to either a Final part or an (untouched) OG part
    # actually recorded on the run -- no orphaned/stale Final file from
    # before the rebuild should remain.
    expected_names = {p.file_path.name for p in run.final_parts} | {p.file_path.name for p in run.og_parts}
    actual_names = {f.name for f in files_after}
    assert actual_names == expected_names


# TEST 10b - REGRESSION: a decision must still succeed even after the
# original conversion workspace has already been cleaned up (the normal
# case in the real app -- the review dialog only ever appears after the
# build, and MainWindow never passes keep_temp=True). Found via the
# full-pipeline test below initially failing with FileNotFoundError;
# this test pins the fix (re-extracting from the permanent OG output)
# down directly and deterministically.
def test_decision_succeeds_after_converted_pdf_path_no_longer_exists(tmp_path):
    config = AppConfig()
    run = _build_run(tmp_path, config)

    # Simulate workspace cleanup: the original per-document converted
    # PDFs are gone, exactly as they would be after a real build.py run
    # completes and Workspace.cleanup() removes the temp tree.
    for occ in run.occurrences:
        occ.converted_pdf_path.unlink()
        occ.converted_pdf_path = Path("/nonexistent/deleted/workspace/converted.pdf")

    review_decisions.apply_review_decision(run, config, "UM-0001", "excluded", excluded_document_id="D2")

    final_ids = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert final_ids == {"D1"}
    assert run.success is True
    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"

    # The retained document's rebuilt Final PDF still has the right
    # page count -- proving the re-extracted content, not just the
    # bookkeeping, is correct.
    final_pdf_path = run.final_parts[0].file_path
    from pypdf import PdfReader

    assert len(PdfReader(str(final_pdf_path)).pages) == 2


# TEST 11 - full pipeline: run_build() itself populates run.uncertain_matches
# for a real uncertain content-duplicate pair, and applying a decision on
# that real, pipeline-produced run works end to end.
def test_full_pipeline_produces_and_can_decide_a_real_uncertain_match(tmp_path, run_build, monkeypatch):
    monkeypatch.setattr(content_dedup, "_text_similarity", lambda a, b: 0.85)

    # Single-capitalized-word prefixes (not two-or-more consecutive
    # capitalized words) so the name-hint hard veto in pdf_content.py's
    # _NAME_HINT_PATTERN does not fire and mask the mocked similarity.
    folder = tmp_path / "input"
    make_pdf(folder / "one.pdf", pages=1, text_prefix="Shared")
    make_pdf(folder / "two.pdf", pages=1, text_prefix="Content")

    run = run_build(folder)

    assert len(run.uncertain_matches) == 1
    match = run.uncertain_matches[0]
    assert match.kind == "content_duplicate"
    assert match.decision == "undecided"
    assert set(match.excludable_ids) == {match.document_id_a, match.document_id_b}

    one = next(o for o in run.occurrences if o.original_filename == "one.pdf")
    two = next(o for o in run.occurrences if o.original_filename == "two.pdf")
    assert one.needs_review is True and two.needs_review is True
    final_ids_before = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert one.document_id in final_ids_before and two.document_id in final_ids_before

    config = AppConfig()
    review_decisions.apply_review_decision(
        run, config, match.match_id, "excluded", excluded_document_id=two.document_id, reason="chosen redundant"
    )

    final_ids_after = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert one.document_id in final_ids_after
    assert two.document_id not in final_ids_after
    og_ids = {doc_id for p in run.og_parts for doc_id in p.document_ids}
    assert one.document_id in og_ids and two.document_id in og_ids
    assert run.success is True


# TEST 12 - REGRESSION (real user-reported bug): manually excluding a
# document via an uncertain-match decision that has NOTHING to do with a
# separate, already-CONFIRMED content-duplicate relationship must not
# orphan that other relationship. Direct/deterministic reproduction: a
# document already serving as another occurrence's
# content_duplicate_of_document_id gets manually_excluded=True via an
# unrelated match.
def test_manual_exclusion_rescues_orphaned_content_duplicate(tmp_path):
    config = AppConfig()
    run = _build_run(tmp_path, config)  # gives us D1, D2 + match UM-0001 (D1 vs D2, both excludable)

    # A THIRD occurrence, already automatically excluded by the (earlier,
    # unrelated) content-aware dedup pass as a confirmed duplicate of D1.
    y_pdf = make_pdf(tmp_path / "Y.pdf", pages=2, text_prefix="Y")
    occ_y = _occ("D3", y_pdf)
    occ_y.needs_review = False
    occ_y.is_content_duplicate = True
    occ_y.content_duplicate_of_document_id = "D1"
    occ_y.duplicate_detection_method = "content_equivalent"
    occ_y.duplicate_confidence = 0.97
    run.occurrences.append(occ_y)

    # D3 belongs in OG regardless of its Final status, exactly as it
    # would from a real build -- add its own OG part.
    # A distinct identity is used here purely so this second, separate
    # write_package() call produces a differently-named file than the
    # D1/D2 OG part above -- a real build only ever calls write_package()
    # once for the complete OG document list.
    y_og_parts = merging.write_package(
        [occ_y], run.output_path / "Final", PackageIdentity(last_name="Test", first_name="Borrower-D3"),
        naming.OG_PACKAGE_KIND, "OG",
        config.max_pages_per_part, config.max_size_bytes_per_part,
    )
    next_index = len(run.og_parts) + 1
    for part in y_og_parts:
        part.index = next_index
        occ_y.og_part_index = next_index
        next_index += 1
    run.og_parts.extend(y_og_parts)

    assert occ_y.included_in_final is False  # sanity: genuinely excluded beforehand

    # The user reviews UM-0001 (D1 vs D2) -- entirely unrelated to D3/Y --
    # and chooses to exclude D1.
    review_decisions.apply_review_decision(run, config, "UM-0001", "excluded", excluded_document_id="D1")

    # D3/Y must be rescued: it is no longer provably redundant with
    # anything present in Final, so it must come back rather than be
    # silently lost.
    assert occ_y.is_content_duplicate is False
    assert occ_y.content_duplicate_of_document_id is None
    assert occ_y.included_in_final is True
    final_ids = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert "D3" in final_ids
    assert "D1" not in final_ids  # D1 itself is still the one excluded
    assert "D2" in final_ids

    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"


# TEST 13 - same regression, but through the real end-to-end pipeline,
# mirroring the actual reported shape: a confirmed content-duplicate pair
# (via real, unmocked exact-normalized-text matching) plus a SEPARATE
# uncertain match that offers the confirmed pair's retained canonical as
# an excludable choice.
def test_full_pipeline_manual_exclusion_rescues_orphaned_content_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(content_dedup, "_text_similarity", lambda a, b: 0.85)

    folder = tmp_path / "input"
    make_pdf(folder / "confirmed_a.pdf", pages=1, text_prefix="Shared", metadata={"/CustomTag": "a"})
    make_pdf(folder / "confirmed_b.pdf", pages=1, text_prefix="Shared", metadata={"/CustomTag": "b"})
    make_pdf(folder / "other_side.pdf", pages=1, text_prefix="Different")

    from lender_package_builder.cli import build_package

    config = AppConfig()
    run = build_package(input_path=folder, output_dir=tmp_path / "output", config=config, progress=False)

    dup = next(o for o in run.occurrences if o.original_filename in ("confirmed_a.pdf", "confirmed_b.pdf")
               and o.is_content_duplicate)
    canonical = next(o for o in run.occurrences if o.original_filename in ("confirmed_a.pdf", "confirmed_b.pdf")
                      and not o.is_content_duplicate)
    assert dup.content_duplicate_of_document_id == canonical.document_id

    match = next(m for m in run.uncertain_matches if canonical.document_id in m.excludable_ids)

    review_decisions.apply_review_decision(
        run, config, match.match_id, "excluded", excluded_document_id=canonical.document_id
    )

    assert dup.is_content_duplicate is False
    assert dup.included_in_final is True
    final_ids = {doc_id for p in run.final_parts for doc_id in p.document_ids}
    assert dup.document_id in final_ids
    assert canonical.document_id not in final_ids
    assert run.success is True
    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"
