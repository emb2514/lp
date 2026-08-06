"""User-facing output naming: the main output folder, the Final and
Original Lender Package filenames, and extracted key-document
filenames -- all derived from one `PackageIdentity` (last name, first
name, loan number, adverse status, lender) so every output name in the
app comes from a single, consistently-formatted place.

`identity.lender` (e.g. "UWM", "Freedom", "Rocket Mortgage") appears as
its own segment in filenames for documents tied to the loan transaction
itself (Lender Package, Original Lender Package, Closing Disclosure,
Loan Estimate, ALTA Settlement Statement, loan non-proceeding documents)
-- never for Government ID (identifies the borrower personally, not the
transaction) or the two Mortgage-Unity-specific documents, MU Privacy
Policy and MU MA Broker Addendum (Mortgage Unity's own company/
regulatory documents, not tied to whichever wholesale lender this loan
went to) -- see each caller's `include_lender=False` in
`key_documents.py`. Omitted cleanly wherever blank, exactly like every
other optional identity field.

Convention: comma-separated components, no underscores, e.g.
"True, Michael, 6192278785" or "True, Michael, Lender Package,
Part 001.pdf". Every function here is a pure string transform -- no
filesystem access except `resolve_versioned_output_dir`, which only
*reads* (`Path.exists()`) to find the first free ", vN" suffix.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import PackageIdentity

# Windows reserves these characters in file/folder names, plus the C0
# control range. A trailing dot or space is also invalid (and silently
# stripped by Windows itself) -- stripped explicitly here so the name
# this app records/displays always matches what actually lands on disk.
_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE_RUN = re.compile(r"\s+")

FINAL_PACKAGE_KIND = "Lender Package"
OG_PACKAGE_KIND = "Original Lender Package"
UNCONVERTED_FILES_FOLDER_NAME = "Unconverted Files"
IMPORTANT_DOCS_FOLDER_NAME = "Important Docs"
INCOMPLETE_CANCELLED_OUTPUT_FOLDER_NAME = "Incomplete Cancelled Output"


def sanitize_component(value: str) -> str:
    """Removes characters Windows cannot store in a file/folder name,
    collapses internal whitespace runs to a single space, and trims
    leading/trailing whitespace and dots. Never raises -- an empty or
    fully-invalid input simply becomes "".
    """

    value = _INVALID_WINDOWS_CHARS.sub("", value)
    value = _WHITESPACE_RUN.sub(" ", value)
    return value.strip(" .")


def clean_identity(identity: PackageIdentity) -> PackageIdentity:
    """Returns a copy of `identity` with every text field sanitized."""

    return PackageIdentity(
        last_name=sanitize_component(identity.last_name),
        first_name=sanitize_component(identity.first_name),
        loan_number=sanitize_component(identity.loan_number),
        is_adverse=identity.is_adverse,
        lender=sanitize_component(identity.lender),
    )


def _borrower_prefix(identity: PackageIdentity) -> str:
    """"Last Name, First Name" with either half omitted cleanly if
    blank, and no leading/trailing/doubled comma either way.
    """

    identity = clean_identity(identity)
    return ", ".join(p for p in (identity.last_name, identity.first_name) if p)


def main_folder_name(identity: PackageIdentity) -> str:
    """The main output folder name, e.g. "True, Michael, 6192278785" or,
    for a non-proceeding file, "True, Michael, Adverse, 6192278785".
    Falls back to a generic name only when no identity field at all was
    provided (defense in depth -- the GUI always collects at least a
    last name before processing).
    """

    identity = clean_identity(identity)
    parts = [p for p in (identity.last_name, identity.first_name) if p]
    if identity.is_adverse:
        parts.append("Adverse")
    if identity.loan_number:
        parts.append(identity.loan_number)
    return ", ".join(parts) if parts else "Lender Package"


def resolve_versioned_output_dir(parent: Path, base_name: str) -> Path:
    """Returns `parent / base_name` if free, otherwise the first free
    `parent / "{base_name}, vN"` (N = 2, 3, ...). Never returns a path
    that already exists -- an earlier run's output is never silently
    overwritten.
    """

    candidate = parent / base_name
    if not candidate.exists():
        return candidate
    version = 2
    while True:
        candidate = parent / f"{base_name}, v{version}"
        if not candidate.exists():
            return candidate
        version += 1


def package_part_filename(
    identity: PackageIdentity, kind: str, part_index: int, total_parts: int
) -> str:
    """Final/Original Lender Package filename for one output part, e.g.
    "True, Michael, Lender Package, UWM, 6192278785.pdf" (lender and/or
    loan number omitted cleanly when blank).

    Single-part packages omit the part suffix entirely; multi-part
    packages append a three-digit, 1-based part number last
    ("..., Lender Package, UWM, 6192278785, Part 001.pdf").
    """

    identity = clean_identity(identity)
    prefix = _borrower_prefix(identity)
    segments = [s for s in (prefix, kind, identity.lender, identity.loan_number) if s]
    name = ", ".join(segments)
    if total_parts > 1:
        name = f"{name}, Part {part_index:03d}"
    return sanitize_component(name) + ".pdf"


def key_document_filename(
    identity: PackageIdentity,
    document_name: str,
    *,
    signature_status: str | None = None,
    loan_number: str | None = None,
    copy_suffix: str | None = None,
    person_name_override: str | None = None,
    include_lender: bool = True,
) -> str:
    """Standalone extracted key-document filename, e.g.
    "True, Michael, Closing Disclosure, Signed, UWM, 6192278785.pdf".

    `person_name_override` lets a document belonging to someone other
    than the primary borrower (e.g. a co-borrower's Government ID) use
    that person's own name instead of `identity`'s, without otherwise
    changing the convention.

    `include_lender=False` (Government ID only) omits the lender segment
    entirely -- a driver's license/passport/state ID identifies the
    borrower personally, not the loan transaction, so it is never
    attributed to a specific lender the way a Closing Disclosure, Loan
    Estimate, ALTA Settlement Statement, or non-proceeding notice is.
    """

    prefix = sanitize_component(person_name_override) if person_name_override else _borrower_prefix(identity)
    identity = clean_identity(identity)
    segments = [s for s in (prefix, document_name, signature_status) if s]
    if include_lender and identity.lender:
        segments.append(identity.lender)
    resolved_loan_number = sanitize_component(loan_number) if loan_number is not None else identity.loan_number
    if resolved_loan_number:
        segments.append(resolved_loan_number)
    if copy_suffix:
        segments.append(copy_suffix)
    return sanitize_component(", ".join(segments)) + ".pdf"
