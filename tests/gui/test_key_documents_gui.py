"""GUI tests for MILESTONE 4: the completed-run screen's key-document/
wet-signature stat rows and the "Open Final Package" action.
"""

from __future__ import annotations

from pathlib import Path

from lender_package_builder.models import (
    IntegrityCheckResult,
    KeyDocumentMatch,
    OutputPart,
    RunResult,
)


def _run_with_key_documents(tmp_path: Path, wet_signed_cd: bool) -> RunResult:
    output_path = tmp_path / "output"
    final_dir = output_path / "Final"
    final_dir.mkdir(parents=True)
    (output_path / "Reports").mkdir()

    final_pdf = final_dir / "part1.pdf"
    final_pdf.write_bytes(b"%PDF-1.4 fake")
    final_part = OutputPart(
        package="Final", index=1, file_path=final_pdf, document_ids=["DOC-000001"], page_count=1, file_size_bytes=10,
    )

    matches = [
        KeyDocumentMatch(
            match_id="KD-0001",
            category="closing_disclosure",
            subtype=None,
            confidence_band="Confirmed",
            confidence=1.0,
            document_id="DOC-000001",
            original_filename="doc.pdf",
            borrower_name=None,
            reason="test",
            document_page_range=(1, 1),
            signature_status="Signed" if wet_signed_cd else "Unsigned",
        )
    ]

    return RunResult(
        input_path=tmp_path / "input.zip",
        output_path=output_path,
        start_time="t0",
        final_parts=[final_part],
        integrity_checks=[IntegrityCheckResult(name="c", passed=True, detail="ok")],
        key_document_matches=matches,
    )


def test_result_view_shows_key_document_and_wet_signature_stat_rows(window, tmp_path):
    run = _run_with_key_documents(tmp_path, wet_signed_cd=True)
    window.result_view.set_result(run, is_warning=False)

    rows = {
        window.result_view._stats_layout.itemAtPosition(row, 0).widget().text():
            window.result_view._stats_layout.itemAtPosition(row, 1).widget().text()
        for row in range(window.result_view._stats_layout.rowCount())
    }
    assert rows["Key documents found"] == "1"
    assert rows["Wet-signed documents found"] == "1"
    assert rows["Wet-signed Closing Disclosure"] == "Found"


def test_result_view_shows_not_found_when_no_wet_signed_closing_disclosure(window, tmp_path):
    run = _run_with_key_documents(tmp_path, wet_signed_cd=False)
    window.result_view.set_result(run, is_warning=False)

    rows = {
        window.result_view._stats_layout.itemAtPosition(row, 0).widget().text():
            window.result_view._stats_layout.itemAtPosition(row, 1).widget().text()
        for row in range(window.result_view._stats_layout.rowCount())
    }
    assert rows["Wet-signed documents found"] == "None found in the Final lender package"
    assert rows["Wet-signed Closing Disclosure"] == "Not found"


def test_open_final_package_button_opens_first_part(window, tmp_path, monkeypatch):
    run = _run_with_key_documents(tmp_path, wet_signed_cd=True)

    opened_urls = []
    monkeypatch.setattr(
        "lender_package_builder.gui.os_actions.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url.toLocalFile()) or True,
    )

    window.result_view.set_result(run, is_warning=False)
    assert window.result_view.open_final_package_button.isEnabled()
    assert window.result_view.open_final_package_button.text() == "Open Final Package"

    window.result_view.open_final_package_button.click()
    assert [Path(u) for u in opened_urls] == [run.final_parts[0].file_path]


def test_open_final_package_button_label_shows_part_count_when_split(window, tmp_path):
    run = _run_with_key_documents(tmp_path, wet_signed_cd=True)
    second_part = OutputPart(
        package="Final", index=2, file_path=run.output_path / "Final" / "part2.pdf",
        document_ids=["DOC-000002"], page_count=1, file_size_bytes=10,
    )
    run.final_parts.append(second_part)

    window.result_view.set_result(run, is_warning=False)
    assert window.result_view.open_final_package_button.text() == "Open Final Package (Part 1 of 2)"
