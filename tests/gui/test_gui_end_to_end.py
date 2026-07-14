from __future__ import annotations

import pytest
from pypdf import PdfReader

from fixtures.builders import make_pdf, make_zip


# TEST 19 - GUI END-TO-END SYNTHETIC PACKAGE
#
# Marked to opt out of the autouse synchronous-worker fixture (see
# tests/gui/conftest.py) -- this test's whole point is to prove the
# REAL background QThread worker path works end to end.
@pytest.mark.real_background_thread
def test_synthetic_package_completes_through_real_gui_worker(window, tmp_path, qtbot):
    unique_a = tmp_path / "unique_a.pdf"
    unique_b = tmp_path / "unique_b.pdf"
    dup_original = tmp_path / "dup_original.pdf"
    dup_copy = tmp_path / "dup_copy.pdf"
    make_pdf(unique_a, pages=3, text_prefix="Unique A")
    make_pdf(unique_b, pages=2, text_prefix="Unique B")
    make_pdf(dup_original, pages=5, text_prefix="Shared content")

    zip_path = tmp_path / "lender_package.zip"
    make_zip(
        zip_path,
        [
            ("unique_a.pdf", unique_a.read_bytes()),
            ("dup_original.pdf", dup_original.read_bytes()),
            ("unique_b.pdf", unique_b.read_bytes()),
            ("dup_copy.pdf", dup_original.read_bytes()),  # byte-identical to dup_original
        ],
    )

    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    qtbot.waitUntil(lambda: window.current_selection.estimate is not None, timeout=5000)
    assert window.build_button.isEnabled()

    window._on_build_clicked()
    assert window.is_processing is True

    qtbot.waitUntil(lambda: not window.is_processing, timeout=30000)

    # GUI reaches a completion state (success, since no unsupported files here).
    assert window.stack.currentWidget() is window.result_view

    run = window.result_view._run
    assert run is not None
    assert run.success is True

    # OG and Final outputs exist on disk.
    assert run.output_path.exists()
    for part in run.og_parts:
        assert part.file_path.exists()
        assert len(PdfReader(str(part.file_path)).pages) >= 1
    for part in run.final_parts:
        assert part.file_path.exists()

    # Reports exist.
    reports_dir = run.output_path / "Reports"
    assert (reports_dir / "Processing_Report.txt").exists()
    assert (reports_dir / "Duplicate_Removal_Log.txt").exists()
    assert (reports_dir / "Processing_Manifest.json").exists()

    # All integrity checks pass.
    assert all(check.passed for check in run.integrity_checks)

    # Exact duplicate behavior: 4 source occurrences in OG, 3 unique in Final.
    og_count = sum(len(p.document_ids) for p in run.og_parts)
    final_count = sum(len(p.document_ids) for p in run.final_parts)
    assert og_count == 4
    assert final_count == 3

    # No source document is split: every part's page count matches the sum
    # of its documents' recorded page counts (mirrors the Stage 1 check).
    occ_by_id = {o.document_id: o for o in run.occurrences}
    for part in run.og_parts + run.final_parts:
        expected = sum(occ_by_id[d].converted_page_count or 0 for d in part.document_ids)
        assert part.page_count == expected
