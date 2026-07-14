from __future__ import annotations

from fixtures.builders import make_pdf, make_txt

from lender_package_builder.progress import ProgressEvent, ProgressSeverity, ProgressStage


def test_progress_callback_receives_structured_events_in_stage_order(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "a.pdf", pages=3)
    make_pdf(folder / "b.pdf", pages=2)

    events: list[ProgressEvent] = []
    run = run_build(folder, progress_callback=events.append)

    assert run.success is True
    assert events, "expected at least one progress event"
    assert all(isinstance(e, ProgressEvent) for e in events)

    stages_seen = [e.stage for e in events]
    # Stages must appear in pipeline order (allowing repeats within a stage).
    expected_order = [
        ProgressStage.PREFLIGHT,
        ProgressStage.DISCOVERING_FILES,
        ProgressStage.DETECTING_DUPLICATES,
        ProgressStage.CONVERTING_DOCUMENTS,
        ProgressStage.BUILDING_OG,
        ProgressStage.BUILDING_FINAL,
        ProgressStage.RUNNING_INTEGRITY_CHECKS,
        ProgressStage.WRITING_REPORTS,
        ProgressStage.COMPLETE,
    ]
    dedup_seen = []
    for stage in stages_seen:
        if not dedup_seen or dedup_seen[-1] != stage:
            dedup_seen.append(stage)
    assert dedup_seen == expected_order

    last_event = events[-1]
    assert last_event.stage == ProgressStage.COMPLETE
    assert last_event.severity == ProgressSeverity.INFO


def test_progress_events_carry_current_total_and_item_during_conversion(tmp_path, run_build):
    folder = tmp_path / "input"
    make_txt(folder / "one.txt", "first\n")
    make_txt(folder / "two.txt", "second\n")
    make_txt(folder / "three.txt", "third\n")

    events: list[ProgressEvent] = []
    run_build(folder, progress_callback=events.append)

    conversion_events = [
        e for e in events if e.stage == ProgressStage.CONVERTING_DOCUMENTS and e.current_item is not None
    ]
    assert len(conversion_events) == 3
    for i, event in enumerate(conversion_events, start=1):
        assert event.current == i
        assert event.total == 3
        assert event.current_item in ("one.txt", "two.txt", "three.txt")


def test_progress_callback_is_optional_and_backward_compatible(tmp_path, run_build):
    folder = tmp_path / "input"
    make_txt(folder / "solo.txt", "content\n")

    # No progress_callback passed at all -- must behave exactly as before.
    run = run_build(folder)
    assert run.success is True


def test_progress_callback_exception_does_not_break_processing(tmp_path, run_build):
    folder = tmp_path / "input"
    make_txt(folder / "solo.txt", "content\n")

    def bad_callback(event: ProgressEvent) -> None:
        raise RuntimeError("simulated GUI bug")

    run = run_build(folder, progress_callback=bad_callback)
    assert run.success is True


def test_progress_events_do_not_change_run_result(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "a.pdf", pages=4)
    make_pdf(folder / "b.pdf", pages=4)  # identical content -> duplicate

    events: list[ProgressEvent] = []
    with_callback = run_build(folder, output_dir=tmp_path / "out_with_cb", progress_callback=events.append)
    without_callback = run_build(folder, output_dir=tmp_path / "out_without_cb")

    def summarize(run):
        return (
            sum(len(p.document_ids) for p in run.og_parts),
            sum(len(p.document_ids) for p in run.final_parts),
            sum(p.page_count for p in run.og_parts),
            sum(p.page_count for p in run.final_parts),
            run.success,
        )

    assert summarize(with_callback) == summarize(without_callback)
    assert events  # the callback was actually invoked
