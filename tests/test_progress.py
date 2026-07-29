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
        # RC2: content-aware duplicate detection (Levels 2-4), merged-
        # document overlap detection, and version classification (Level
        # 5), all run between Building OG and Building Final. Always
        # emitted -- even with content-aware dedup disabled via config,
        # each stage still emits one "skipped" event, so this sequence
        # is stable regardless of that setting.
        ProgressStage.FINGERPRINTING_CONTENT,
        ProgressStage.DETECTING_CONTENT_DUPLICATES,
        ProgressStage.ANALYZING_MERGED_PACKAGES,
        ProgressStage.CLASSIFYING_VERSIONS,
        ProgressStage.BUILDING_FINAL,
        # MILESTONE 4: key-document page locator/extraction, run once
        # Final is settled, before integrity checks.
        ProgressStage.LOCATING_KEY_DOCUMENTS,
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


def test_progress_stage_order_stable_with_content_aware_dedup_disabled(tmp_path, run_build, config):
    import dataclasses

    folder = tmp_path / "input"
    make_pdf(folder / "a.pdf", pages=3)
    make_pdf(folder / "b.pdf", pages=2)

    disabled_config = dataclasses.replace(config, enable_content_aware_dedup=False)
    events: list[ProgressEvent] = []
    run = run_build(folder, config=disabled_config, progress_callback=events.append)

    assert run.success is True
    stages_seen = [e.stage for e in events]
    assert ProgressStage.FINGERPRINTING_CONTENT in stages_seen
    assert ProgressStage.DETECTING_CONTENT_DUPLICATES in stages_seen
    assert ProgressStage.ANALYZING_MERGED_PACKAGES in stages_seen
    assert ProgressStage.CLASSIFYING_VERSIONS in stages_seen
    assert run.content_duplicate_groups == []
    assert run.document_families == []
    assert run.overlap_findings == []


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


def test_progress_events_carry_current_total_and_item_during_fingerprinting(tmp_path, run_build):
    # Real user reports (45+ minutes on "Analyzing document content" with
    # no visible movement): `build_fingerprints` used to emit exactly one
    # event at the start of this stage and one at the end, however long it
    # actually took, so the progress panel looked frozen for the entire
    # slowest stage in the pipeline. It must now report per-document
    # progress the same way CONVERTING_DOCUMENTS already does.
    folder = tmp_path / "input"
    make_pdf(folder / "a.pdf", pages=3)
    make_pdf(folder / "b.pdf", pages=2)
    make_pdf(folder / "c.pdf", pages=1)

    events: list[ProgressEvent] = []
    run_build(folder, progress_callback=events.append)

    fingerprint_events = [
        e for e in events if e.stage == ProgressStage.FINGERPRINTING_CONTENT and e.current_item is not None
    ]
    assert len(fingerprint_events) == 3
    for i, event in enumerate(fingerprint_events, start=1):
        assert event.current == i
        assert event.total == 3
        assert event.current_item in ("a.pdf", "b.pdf", "c.pdf")


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
