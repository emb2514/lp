"""Regression tests for a real user-reported document type: MISMO/ULDD
loan-data XML delivered as a `.txt` file (a real sample: a Loan Quality
Advisor ULDD Request). "it would be like one of these types of docs
like i need it to be readable."

These files are routinely a single line tens of thousands of characters
long with no whitespace at all. `text.py`'s existing behavior --
wrapping at a fixed character width -- chops tags and values at
arbitrary points with no relationship to the document's actual
structure, producing something unreadable. `_pretty_print_if_xml`
detects real XML and reformats it with proper indentation first.
"""

from __future__ import annotations

from fixtures.builders import make_txt, read_pdf_text

from lender_package_builder.conversion import text as text_conv
from lender_package_builder.models import ProcessingStatus, SourceOccurrence

_REAL_SAMPLE_XML = (
    '<MESSAGE MISMOReferenceModelIdentifier="3.0.0.263.12" '
    'xmlns="http://www.mismo.org/residential/2009/schemas">'
    "<DEAL_SETS><DEAL_SET><DEALS><DEAL><COLLATERALS><COLLATERAL><PROPERTIES><PROPERTY>"
    "<ADDRESS><AddressLineText>34 W Range Rd</AddressLineText><CityName>Effingham</CityName>"
    "<StateCode>NH</StateCode></ADDRESS>"
    "<PROPERTY_VALUATIONS><PROPERTY_VALUATION><PROPERTY_VALUATION_DETAIL>"
    "<PropertyValuationAmount>375000</PropertyValuationAmount>"
    "</PROPERTY_VALUATION_DETAIL></PROPERTY_VALUATION></PROPERTY_VALUATIONS>"
    "</PROPERTY></PROPERTIES></COLLATERAL></COLLATERALS></DEAL></DEALS></DEAL_SET></DEAL_SETS>"
    "</MESSAGE>"
)


def _txt_occurrence(path) -> SourceOccurrence:
    return SourceOccurrence(
        document_id="D1",
        traversal_index=1,
        original_filename=path.name,
        original_relative_path=path.name,
        original_extension=".txt",
        original_size_bytes=path.stat().st_size,
        status=ProcessingStatus.DISCOVERED,
        extracted_path=path,
    )


# ---------------------------------------------------------------------
# _pretty_print_if_xml -- direct unit coverage
# ---------------------------------------------------------------------


def test_pretty_print_if_xml_formats_real_mismo_sample():
    pretty = text_conv._pretty_print_if_xml(_REAL_SAMPLE_XML)

    assert pretty is not None
    lines = pretty.split("\n")
    assert len(lines) > 5, "a single unbroken line was not actually reformatted"
    assert all(len(line) < len(_REAL_SAMPLE_XML) for line in lines)
    # Real structure is now visible line-by-line, not buried in one blob.
    assert any("AddressLineText" in line for line in lines)
    assert any("34 W Range Rd" in line for line in lines)
    # Nesting is reflected via indentation.
    address_line = next(line for line in lines if "34 W Range Rd" in line)
    root_line = next(line for line in lines if line.strip().startswith("<MESSAGE"))
    assert len(address_line) - len(address_line.lstrip(" ")) > len(root_line) - len(root_line.lstrip(" "))


def test_pretty_print_if_xml_returns_none_for_ordinary_text():
    ordinary = "This is a perfectly ordinary text file with no XML in it at all."
    assert text_conv._pretty_print_if_xml(ordinary) is None


def test_pretty_print_if_xml_returns_none_for_malformed_xml_like_text():
    # Starts with "<" but is not well-formed XML -- must never guess or
    # crash, just decline and let the caller fall back to plain text.
    malformed = "<not really xml, just some text that starts with a bracket and rambles on."
    assert text_conv._pretty_print_if_xml(malformed) is None


def test_pretty_print_if_xml_returns_none_for_empty_text():
    assert text_conv._pretty_print_if_xml("") is None
    assert text_conv._pretty_print_if_xml("   ") is None


# ---------------------------------------------------------------------
# convert() end-to-end
# ---------------------------------------------------------------------


def test_single_line_xml_txt_file_converts_to_readable_indented_pdf(tmp_path):
    source = make_txt(tmp_path / "ULDD_Request.txt", _REAL_SAMPLE_XML)
    occ = _txt_occurrence(source)
    dest = tmp_path / "out.pdf"

    result = text_conv.convert(occ, dest, None)

    assert result.outcome.value == "success"
    assert any("contains XML data" in w for w in result.warnings)

    text = read_pdf_text(dest)
    assert "AddressLineText" in text
    assert "34 W Range Rd" in text
    assert "375000" in text
    # The raw, unbroken single-line form must never appear verbatim --
    # confirms it was actually reformatted, not just passed through.
    assert _REAL_SAMPLE_XML not in text.replace("\n", "")


def test_ordinary_txt_file_is_unaffected_by_the_xml_check(tmp_path):
    # Real safety requirement: this fix must never change behavior for
    # genuinely ordinary text files.
    source = make_txt(tmp_path / "notes.txt", "Line one\nLine two\nJust ordinary notes here.\n")
    occ = _txt_occurrence(source)
    dest = tmp_path / "out.pdf"

    result = text_conv.convert(occ, dest, None)

    assert result.outcome.value == "success"
    assert not any("XML" in w for w in result.warnings)
    text = read_pdf_text(dest)
    assert "Line one" in text
    assert "Just ordinary notes here" in text


def test_long_wrapped_ordinary_text_still_wraps_as_before(tmp_path):
    # Pre-existing behavior (long non-XML lines still get hard-wrapped)
    # must be completely unchanged.
    source = make_txt(tmp_path / "long.txt", "x" * 300)
    occ = _txt_occurrence(source)
    dest = tmp_path / "out.pdf"

    result = text_conv.convert(occ, dest, None)
    assert result.outcome.value == "success"
    assert not any("XML" in w for w in result.warnings)
