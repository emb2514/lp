"""Dedicated unit tests for the 5 RC2-added integrity checks in
validation.py:

  - _check_final_contains_all_included
  - _check_no_unexplained_removal
  - _check_needs_review_never_excluded
  - _check_content_duplicate_retained_exists
  - _check_contained_in_document_retained_exists

Each of these is already exercised indirectly by end-to-end tests
elsewhere (via `run.integrity_checks`, always expected to pass on a
healthy run), but only ever on the happy path. These tests call the
check functions directly with hand-built SourceOccurrence objects so
each check's FAILURE branch -- proving it actually catches the specific
safety violation it exists to catch -- is exercised too, not just its
pass branch.
"""

from __future__ import annotations

from lender_package_builder import validation
from lender_package_builder.models import OutputPart, ProcessingStatus, SourceOccurrence


def _occ(document_id: str, traversal_index: int = 1, **overrides) -> SourceOccurrence:
    defaults = dict(
        document_id=document_id,
        traversal_index=traversal_index,
        original_filename=f"{document_id}.pdf",
        original_relative_path=f"{document_id}.pdf",
        original_extension=".pdf",
        original_size_bytes=100,
        original_sha256=f"hash-{document_id}",
        status=ProcessingStatus.CONVERTED,
        converted_page_count=1,
    )
    defaults.update(overrides)
    return SourceOccurrence(**defaults)


def _part(package: str, document_ids: list[str]) -> OutputPart:
    return OutputPart(package=package, index=1, file_path=__import__("pathlib").Path("/tmp/x.pdf"),
                       document_ids=document_ids, page_count=len(document_ids))


# --- _check_final_contains_all_included ---

def test_final_contains_all_included_passes_when_every_eligible_doc_present():
    a = _occ("A")
    b = _occ("B")
    final_parts = [_part("Final", ["A", "B"])]
    result = validation._check_final_contains_all_included([a, b], final_parts)
    assert result.passed is True


def test_final_contains_all_included_fails_when_an_eligible_doc_is_missing():
    a = _occ("A")
    b = _occ("B")
    final_parts = [_part("Final", ["A"])]  # B is eligible (included_in_final defaults True) but missing
    result = validation._check_final_contains_all_included([a, b], final_parts)
    assert result.passed is False
    assert "B" in result.detail


# --- _check_no_unexplained_removal ---

def test_no_unexplained_removal_passes_for_a_properly_explained_exact_duplicate():
    retained = _occ("A")
    removed = _occ("B", is_duplicate=True, duplicate_of_document_id="A")
    result = validation._check_no_unexplained_removal([retained, removed])
    assert result.passed is True


def test_no_unexplained_removal_passes_for_a_properly_explained_content_duplicate():
    retained = _occ("A")
    removed = _occ(
        "B",
        is_content_duplicate=True,
        content_duplicate_of_document_id="A",
        duplicate_detection_method="normalized_pdf",
    )
    result = validation._check_no_unexplained_removal([retained, removed])
    assert result.passed is True


def test_no_unexplained_removal_passes_for_portfolio_container():
    container = _occ("A", is_portfolio_container=True)
    result = validation._check_no_unexplained_removal([container])
    assert result.passed is True


def test_no_unexplained_removal_passes_for_contained_in_merged_document():
    container = _occ("A")
    contained = _occ("B", is_contained_in_merged_document=True, contained_in_document_id="A")
    result = validation._check_no_unexplained_removal([container, contained])
    assert result.passed is True


def test_no_unexplained_removal_fails_when_exclusion_flag_set_without_a_reason():
    # is_duplicate=True but duplicate_of_document_id is missing -- excluded
    # from Final (via included_in_final) with no auditable explanation.
    broken = _occ("B", is_duplicate=True, duplicate_of_document_id=None)
    result = validation._check_no_unexplained_removal([broken])
    assert result.passed is False
    assert "B" in result.detail


def test_no_unexplained_removal_fails_when_content_duplicate_missing_method():
    broken = _occ(
        "B",
        is_content_duplicate=True,
        content_duplicate_of_document_id="A",
        duplicate_detection_method=None,  # missing -- not fully explained
    )
    result = validation._check_no_unexplained_removal([broken])
    assert result.passed is False
    assert "B" in result.detail


# --- _check_needs_review_never_excluded ---

def test_needs_review_never_excluded_passes_when_flagged_doc_stays_in_final():
    flagged = _occ("A", needs_review=True, review_reason="uncertain match")
    result = validation._check_needs_review_never_excluded([flagged])
    assert result.passed is True


def test_needs_review_never_excluded_fails_when_flagged_doc_is_also_excluded():
    # needs_review=True combined with an unconditional exclusion reason
    # (is_duplicate, which is NOT needs_review-guarded like the RC2
    # content-aware fields are) -- this is exactly the "keep both when
    # uncertain" violation this check exists to catch.
    violating = _occ("A", needs_review=True, review_reason="uncertain", is_duplicate=True,
                      duplicate_of_document_id="Z")
    result = validation._check_needs_review_never_excluded([violating])
    assert result.passed is False
    assert "A" in result.detail


# --- _check_content_duplicate_retained_exists ---

def test_content_duplicate_retained_exists_passes_when_target_is_in_final():
    retained = _occ("A")
    dup = _occ("B", is_content_duplicate=True, content_duplicate_of_document_id="A")
    occ_by_id = {"A": retained, "B": dup}
    result = validation._check_content_duplicate_retained_exists([retained, dup], occ_by_id)
    assert result.passed is True


def test_content_duplicate_retained_exists_fails_when_target_is_missing():
    dup = _occ("B", is_content_duplicate=True, content_duplicate_of_document_id="NONEXISTENT")
    occ_by_id = {"B": dup}
    result = validation._check_content_duplicate_retained_exists([dup], occ_by_id)
    assert result.passed is False
    assert "B" in result.detail


def test_content_duplicate_retained_exists_fails_when_target_itself_excluded():
    # A references itself-excluded document as its "retained" copy --
    # a broken chain (A is also an exact duplicate of something else).
    broken_target = _occ("A", is_duplicate=True, duplicate_of_document_id="Z")
    dup = _occ("B", is_content_duplicate=True, content_duplicate_of_document_id="A")
    occ_by_id = {"A": broken_target, "B": dup}
    result = validation._check_content_duplicate_retained_exists([broken_target, dup], occ_by_id)
    assert result.passed is False
    assert "B" in result.detail


# --- _check_contained_in_document_retained_exists ---

def test_contained_in_document_retained_exists_passes_when_container_is_in_final():
    container = _occ("M")
    contained = _occ("A", is_contained_in_merged_document=True, contained_in_document_id="M")
    occ_by_id = {"M": container, "A": contained}
    result = validation._check_contained_in_document_retained_exists([container, contained], occ_by_id)
    assert result.passed is True


def test_contained_in_document_retained_exists_fails_when_container_is_missing():
    contained = _occ("A", is_contained_in_merged_document=True, contained_in_document_id="NONEXISTENT")
    occ_by_id = {"A": contained}
    result = validation._check_contained_in_document_retained_exists([contained], occ_by_id)
    assert result.passed is False
    assert "A" in result.detail


def test_contained_in_document_retained_exists_fails_when_container_itself_excluded():
    broken_container = _occ("M", is_duplicate=True, duplicate_of_document_id="Z")
    contained = _occ("A", is_contained_in_merged_document=True, contained_in_document_id="M")
    occ_by_id = {"M": broken_container, "A": contained}
    result = validation._check_contained_in_document_retained_exists([broken_container, contained], occ_by_id)
    assert result.passed is False
    assert "A" in result.detail


# --- run_integrity_checks end-to-end wiring sanity ---

def test_run_integrity_checks_includes_all_five_new_checks(tmp_path, run_build):
    from fixtures.builders import make_txt

    folder = tmp_path / "input"
    make_txt(folder / "solo.txt", "just one file\n")
    run = run_build(folder)

    check_names = {c.name for c in run.integrity_checks}
    assert "Final contains every occurrence not excluded for a recorded reason" in check_names
    assert "Every Final exclusion has an auditable reason" in check_names
    assert (
        "Occurrences flagged needs_review are never excluded from Final without an explicit human decision"
        in check_names
    )
    assert "Content-duplicate references resolve to a retained Final document" in check_names
    assert "Containment references resolve to a retained Final container" in check_names
    assert "Manual exclusions trace back to a valid, auditable review decision" in check_names
    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"
