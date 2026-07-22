"""Tests for naming.py -- the single source of every user-facing output
name (main folder, Final/Original Lender Package filenames, and
extracted key-document filenames), all derived from one
`PackageIdentity`. See MILESTONE 1 of the naming/folder-structure spec.
"""

from __future__ import annotations

from lender_package_builder import naming
from lender_package_builder.models import PackageIdentity


def _identity(**kwargs) -> PackageIdentity:
    return PackageIdentity(**kwargs)


# TEST 1 - normal (non-adverse) main folder name
def test_main_folder_name_normal():
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785")
    assert naming.main_folder_name(identity) == "True, Michael, 6192278785"


# TEST 2 - adverse/non-proceeding main folder name
def test_main_folder_name_adverse():
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785", is_adverse=True)
    assert naming.main_folder_name(identity) == "True, Michael, Adverse, 6192278785"


# TEST 3 - invalid Windows filename characters are stripped
def test_main_folder_name_strips_invalid_windows_characters():
    identity = _identity(last_name='O"Brien:<Test>', first_name="Mich/ael\\", loan_number="619|2278*785?")
    name = naming.main_folder_name(identity)
    for bad_char in '<>:"/\\|?*':
        assert bad_char not in name
    assert name == "OBrienTest, Michael, 6192278785"


# TEST 4 - missing optional values never produce awkward double commas
def test_main_folder_name_missing_first_name_has_no_double_comma():
    identity = _identity(last_name="True", loan_number="6192278785")
    assert naming.main_folder_name(identity) == "True, 6192278785"
    assert ",," not in naming.main_folder_name(identity)


def test_main_folder_name_missing_loan_number():
    identity = _identity(last_name="True", first_name="Michael")
    assert naming.main_folder_name(identity) == "True, Michael"


def test_main_folder_name_only_last_name():
    identity = _identity(last_name="True")
    assert naming.main_folder_name(identity) == "True"


# TEST 5 - overwrite protection: versioned folder names never collide
def test_resolve_versioned_output_dir_no_collision(tmp_path):
    result = naming.resolve_versioned_output_dir(tmp_path, "True, Michael, 6192278785")
    assert result == tmp_path / "True, Michael, 6192278785"


def test_resolve_versioned_output_dir_increments_version_on_collision(tmp_path):
    base = tmp_path / "True, Michael, 6192278785"
    base.mkdir()
    result = naming.resolve_versioned_output_dir(tmp_path, "True, Michael, 6192278785")
    assert result == tmp_path / "True, Michael, 6192278785, v2"

    (tmp_path / "True, Michael, 6192278785, v2").mkdir()
    result = naming.resolve_versioned_output_dir(tmp_path, "True, Michael, 6192278785")
    assert result == tmp_path / "True, Michael, 6192278785, v3"


def test_resolve_versioned_output_dir_skips_multiple_existing_versions(tmp_path):
    (tmp_path / "True, Michael, 6192278785").mkdir()
    (tmp_path / "True, Michael, 6192278785, v2").mkdir()
    (tmp_path / "True, Michael, 6192278785, v3").mkdir()
    result = naming.resolve_versioned_output_dir(tmp_path, "True, Michael, 6192278785")
    assert result == tmp_path / "True, Michael, 6192278785, v4"
    assert not result.exists()


# TEST 6 - no underscores anywhere in generated names
def test_no_underscores_in_any_generated_name():
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785", is_adverse=True)
    assert "_" not in naming.main_folder_name(identity)
    assert "_" not in naming.package_part_filename(identity, naming.FINAL_PACKAGE_KIND, 1, 1)
    assert "_" not in naming.package_part_filename(identity, naming.OG_PACKAGE_KIND, 1, 2)
    assert "_" not in naming.key_document_filename(identity, "Closing Disclosure", signature_status="Signed")


# TEST 7 - comma placement is always correct (no leading/trailing/doubled commas)
def test_comma_placement_is_clean():
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785")
    for name in (
        naming.main_folder_name(identity),
        naming.package_part_filename(identity, naming.FINAL_PACKAGE_KIND, 1, 1),
        naming.key_document_filename(identity, "Closing Disclosure", signature_status="Signed"),
    ):
        assert not name.startswith(",")
        assert not name.startswith(" ")
        assert ",," not in name
        assert ", ," not in name


# TEST 8 - single-part Final Lender Package filename omits "Part NNN"
def test_final_package_filename_single_part():
    identity = _identity(last_name="True", first_name="Michael")
    assert (
        naming.package_part_filename(identity, naming.FINAL_PACKAGE_KIND, 1, 1)
        == "True, Michael, Lender Package.pdf"
    )


# TEST 9 - split Final Lender Package filenames use three-digit part numbers
def test_final_package_filename_split_parts():
    identity = _identity(last_name="True", first_name="Michael")
    assert (
        naming.package_part_filename(identity, naming.FINAL_PACKAGE_KIND, 1, 3)
        == "True, Michael, Lender Package, Part 001.pdf"
    )
    assert (
        naming.package_part_filename(identity, naming.FINAL_PACKAGE_KIND, 2, 3)
        == "True, Michael, Lender Package, Part 002.pdf"
    )
    assert (
        naming.package_part_filename(identity, naming.FINAL_PACKAGE_KIND, 3, 3)
        == "True, Michael, Lender Package, Part 003.pdf"
    )


# TEST 10 - single-part Original Lender Package filename
def test_original_package_filename_single_part():
    identity = _identity(last_name="True", first_name="Michael")
    assert (
        naming.package_part_filename(identity, naming.OG_PACKAGE_KIND, 1, 1)
        == "True, Michael, Original Lender Package.pdf"
    )


# TEST 11 - split Original Lender Package filenames
def test_original_package_filename_split_parts():
    identity = _identity(last_name="True", first_name="Michael")
    assert (
        naming.package_part_filename(identity, naming.OG_PACKAGE_KIND, 1, 2)
        == "True, Michael, Original Lender Package, Part 001.pdf"
    )
    assert (
        naming.package_part_filename(identity, naming.OG_PACKAGE_KIND, 2, 2)
        == "True, Michael, Original Lender Package, Part 002.pdf"
    )


# TEST 12 - explicit three-digit part numbering (not "Part 10", but "Part 010")
def test_part_numbering_is_three_digits():
    identity = _identity(last_name="True", first_name="Michael")
    name = naming.package_part_filename(identity, naming.FINAL_PACKAGE_KIND, 10, 12)
    assert ", Part 010.pdf" in name
    assert "Part 10." not in name


# TEST 13 - wet-signed key document filename
def test_key_document_filename_wet_signed():
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785")
    assert (
        naming.key_document_filename(identity, "Closing Disclosure", signature_status="Signed")
        == "True, Michael, Closing Disclosure, Signed, 6192278785.pdf"
    )


# TEST 14 - e-signed key document filename
def test_key_document_filename_e_signed():
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785")
    assert (
        naming.key_document_filename(identity, "Closing Disclosure", signature_status="E-Sign")
        == "True, Michael, Closing Disclosure, E-Sign, 6192278785.pdf"
    )


# TEST 15 - unsigned key document filename
def test_key_document_filename_unsigned():
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785")
    assert (
        naming.key_document_filename(identity, "Closing Disclosure", signature_status="Unsigned")
        == "True, Michael, Closing Disclosure, Unsigned, 6192278785.pdf"
    )


# TEST 16 - a key document with no applicable signature section omits it cleanly
def test_key_document_filename_no_signature_section():
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785")
    name = naming.key_document_filename(identity, "MU Privacy Policy")
    assert name == "True, Michael, MU Privacy Policy, 6192278785.pdf"
    assert ",, " not in name
    assert ", ," not in name


# TEST 17 - multiple copies of an otherwise-identical filename use a Copy suffix
def test_key_document_filename_multiple_copies():
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785")
    first = naming.key_document_filename(identity, "Closing Disclosure", signature_status="Unsigned")
    second = naming.key_document_filename(
        identity, "Closing Disclosure", signature_status="Unsigned", copy_suffix="Copy 2"
    )
    assert first != second
    assert second == "True, Michael, Closing Disclosure, Unsigned, 6192278785, Copy 2.pdf"


# TEST 18 - two borrowers' Driver's Licenses use each person's own name
def test_key_document_filename_two_borrowers_drivers_licenses():
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785")
    borrower_one = naming.key_document_filename(identity, "Driver License", signature_status="Front")
    borrower_two = naming.key_document_filename(
        identity, "Driver License", signature_status="Front", person_name_override="Smith, Jane"
    )
    assert borrower_one == "True, Michael, Driver License, Front, 6192278785.pdf"
    assert borrower_two == "Smith, Jane, Driver License, Front, 6192278785.pdf"
    assert borrower_one != borrower_two


# TEST 19 - naming functions are pure: they never touch the filesystem or
# mutate the PackageIdentity passed in (no accidental "source renaming").
def test_naming_functions_never_mutate_identity_or_touch_disk(tmp_path):
    identity = _identity(last_name=" True ", first_name="Michael!!", loan_number="619-227-8785")
    before = (identity.last_name, identity.first_name, identity.loan_number, identity.is_adverse)

    naming.main_folder_name(identity)
    naming.package_part_filename(identity, naming.FINAL_PACKAGE_KIND, 1, 1)
    naming.key_document_filename(identity, "Closing Disclosure", signature_status="Signed")

    after = (identity.last_name, identity.first_name, identity.loan_number, identity.is_adverse)
    assert before == after
    assert list(tmp_path.iterdir()) == []


# TEST 20 - sanitize_component collapses whitespace and strips stray dots
def test_sanitize_component_collapses_whitespace_and_trims():
    assert naming.sanitize_component("  True   Michael  ") == "True Michael"
    assert naming.sanitize_component("Trailing dot.") == "Trailing dot"
    assert naming.sanitize_component("") == ""
