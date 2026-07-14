from __future__ import annotations

from fixtures.builders import make_pdf, make_txt


# TEST 18 - ENGINE REGRESSION
#
# The full Stage 1 suite (tests/test_*.py, run unchanged) is the real
# regression check and is run alongside these GUI tests in the same
# `pytest tests -v` invocation -- see the Stage 2 completion report.
# This test additionally proves, from inside the GUI test tree, that
# the engine Stage 2 calls directly still behaves exactly as Stage 1
# specified (exact-duplicate detection, OG/Final counts) after the
# progress-event API was layered on top of it.
def test_stage1_engine_still_behaves_correctly_after_stage2_changes(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "a.pdf", pages=4)
    # reportlab embeds a non-deterministic ID/timestamp, so two separate
    # make_pdf() calls are not guaranteed byte-identical -- copy the exact
    # bytes to get a genuine, guaranteed exact duplicate.
    (folder / "b.pdf").write_bytes((folder / "a.pdf").read_bytes())
    make_txt(folder / "c.txt", "unique text\n")

    run = run_build(folder)

    assert run.success is True
    og_count = sum(len(p.document_ids) for p in run.og_parts)
    final_count = sum(len(p.document_ids) for p in run.final_parts)
    assert og_count == 3
    assert final_count == 2  # the duplicate PDF excluded from Final only
    assert all(check.passed for check in run.integrity_checks)
