"""Per-page and per-document PDF content fingerprinting.

This is the foundational toolkit that RC2's content-aware duplicate
detection (Levels 2-4, see `content_dedup.py`), merged-document overlap
detection (`overlap_detection.py`), and version classification
(`version_classification.py`) are all built on. It never decides whether
two documents ARE duplicates -- it only extracts comparable signals from
one document/page at a time. Deliberately does not import `pypdfium2`
(page rasterization) or anything else from the "expensive last tier" --
see `pdf_render.py` for that, kept isolated so the cheap tiers never pay
for it.

Blank-page detection here is entirely structural (extracted text, form
fields, annotations, embedded raster images decoded via Pillow) rather
than full-page rasterization: real lender documents are almost always
either digitally-generated text/forms or scanned images, and a page's
content for blankness purposes is fully recoverable from its embedded
objects without rendering the page itself.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import unicodedata

from pypdf import PdfReader
from pypdf.generic import IndirectObject

# ---------------------------------------------------------------------
# Blank-page classification thresholds. Conservative by design: any
# ambiguity must resolve to "not blank" -- a page wrongly treated as
# blank could silently cause a meaningful page to be skipped during
# duplicate comparison (rule: "never blindly remove meaningful
# separator, certification, signature, or intentionally blank pages").
# ---------------------------------------------------------------------

# A page with more than this many non-whitespace text characters is
# never blank, no matter what else is true about it.
_BLANK_MAX_TEXT_CHARS = 3

# An embedded image is only considered itself blank (e.g. a scanned
# blank sheet) when BOTH:
#  (a) fewer than this fraction of its pixels are "ink-dark" (below
#      _BLANK_IMAGE_DARK_LEVEL) -- an absolute-ish ratio, not a coarse
#      global statistic, so a small faint mark (a thin signature stroke,
#      a stamp corner, a barcode) on an otherwise-white page is not
#      diluted into insignificance by the page's total pixel count; and
#  (b) overall pixel variance is low -- catches broad, low-contrast
#      tinting/noise across the whole image that never crosses the dark
#      threshold at any single pixel.
# Defaults are conservative starting points, flagged for empirical
# tuning against real scanned lender documents; when in doubt this must
# fail toward "not blank" (the safe direction -- worst case, two
# genuinely-identical-except-blank-pages documents aren't merged
# automatically and are flagged instead, never the reverse).
_BLANK_IMAGE_DARK_LEVEL = 220  # 0-255 per channel; below this counts as "ink"
_BLANK_IMAGE_MAX_DARK_PIXEL_RATIO = 0.0008
_BLANK_IMAGE_MAX_VARIANCE = 40.0

_DATE_PATTERN = re.compile(
    r"\b("
    r"\d{4}-\d{2}-\d{2}"  # 2026-01-15
    r"|\d{1,2}/\d{1,2}/\d{2,4}"  # 1/15/2026, 01/15/26
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)
_DOLLAR_PATTERN = re.compile(r"\$\s?[\d,]+(?:\.\d{2})?")
# Two-or-more consecutive Capitalized Words -- a crude proper-noun/name
# heuristic (borrower names, addresses). Deliberately case-SENSITIVE, so
# this must run against un-casefolded text (see extract_page_fingerprint,
# which passes the whitespace-collapsed-but-not-casefolded text here,
# not the fully normalized/casefolded text used for hashing/comparison).
# Noisy by nature -- it will also catch ordinary capitalized phrases like
# "Truth In Lending" or "New York" that aren't names at all. That's an
# acceptable cost here: a false-positive hit only makes the hard-veto
# system slightly more conservative (two pages that are actually
# identical content-wise might occasionally need a human glance instead
# of auto-merging), which is the safe direction -- never the dangerous
# one of silently merging two pages that differ in a real borrower name.
_NAME_HINT_PATTERN = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")


@dataclasses.dataclass
class StructuredTokens:
    """Best-effort extracted structured signals from a page's text, used
    as the "hard veto" system in `content_dedup.py`'s per-page
    comparator -- a single differing date or dollar amount must be able
    to veto a match regardless of how similar the surrounding text is.
    This is a defense-in-depth layer, not a guarantee: regex-based
    extraction will not catch every date/amount format, especially from
    OCR'd scans. The medium-confidence "needs_review" band in
    content_dedup.py is the real safety net for anything this misses.
    """

    dates: tuple[str, ...] = ()
    dollar_amounts: tuple[str, ...] = ()
    name_hints: tuple[str, ...] = ()


def extract_structured_tokens(text: str) -> StructuredTokens:
    """`text` should be whitespace-collapsed but NOT casefolded -- the
    name-hint heuristic depends on capitalization.
    """

    dates = tuple(sorted({m.group(0) for m in _DATE_PATTERN.finditer(text)}))
    amounts = tuple(sorted({m.group(0) for m in _DOLLAR_PATTERN.finditer(text)}))
    names = tuple(sorted({m.group(0) for m in _NAME_HINT_PATTERN.finditer(text)}))
    return StructuredTokens(dates=dates, dollar_amounts=amounts, name_hints=names)


@dataclasses.dataclass
class FormFieldSignal:
    name: str
    field_type: str | None  # "/Tx" | "/Btn" | "/Ch" | "/Sig" | None
    value: str | None


@dataclasses.dataclass
class AnnotationSignal:
    subtype: str | None
    contents: str | None
    has_appearance_stream: bool


@dataclasses.dataclass
class EmbeddedImageSignal:
    byte_sha256: str
    perceptual_hash: int | None  # None if the image could not be decoded
    # Mean (R, G, B) in 0-255, None if the image could not be decoded.
    # A difference-hash measures only LOCAL GRADIENTS between adjacent
    # pixels, so it is structurally blind to absolute color: two solid,
    # uniform-color images of any two different colors produce the
    # identical (all-zero) dHash, since there is no internal gradient to
    # compare at all. Found via direct testing -- a solid red test swatch
    # and a solid blue one hashed identically and were falsely matched as
    # the same image. average_color is compared alongside the
    # perceptual hash (weakest-link) in content_dedup.py specifically to
    # close this gap for solid/near-solid images (colored divider/cover
    # pages, unprinted colored stock, etc).
    average_color: tuple[float, float, float] | None
    is_blank: bool
    width: int
    height: int


@dataclasses.dataclass
class BlankClassification:
    is_blank: bool
    confidence: float
    reason: str


@dataclasses.dataclass
class PageFingerprint:
    page_index: int
    normalized_text: str
    text_hash: str  # sha256 of normalized_text, empty string hashes too
    width: float
    height: float
    rotation: int
    form_fields: tuple[FormFieldSignal, ...]
    annotations: tuple[AnnotationSignal, ...]
    has_signature_field: bool
    has_signed_signature: bool
    images: tuple[EmbeddedImageSignal, ...]
    structured_tokens: StructuredTokens
    blank: BlankClassification


@dataclasses.dataclass
class DocumentFingerprint:
    document_id: str
    pages: tuple[PageFingerprint, ...]
    # sha256 over the concatenation of every page's text_hash, in order --
    # the Level-2 "normalized PDF duplicate" fast path.
    normalized_document_hash: str
    has_signature_field: bool
    has_form_fields: bool
    page_dims_signature: tuple[float, float]  # first page's (width, height), rounded

    @property
    def non_blank_page_count(self) -> int:
        return sum(1 for p in self.pages if not p.blank.is_blank)


def _collapse_whitespace(raw: str) -> str:
    """NFKC-normalize and collapse whitespace, but preserve case and
    every character -- this is the text `extract_structured_tokens`
    scans, since its name-hint heuristic depends on capitalization
    (see _NAME_HINT_PATTERN's docstring above).
    """

    normalized = unicodedata.normalize("NFKC", raw)
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_text(raw: str) -> str:
    """Whitespace-collapsed, case-folded -- but never stripped of digits,
    punctuation, or words. Normalization must never erase the exact
    tokens comparison relies on to catch a meaningful difference; it
    only removes incidental whitespace, case, and rendering-order
    differences.
    """

    return _collapse_whitespace(raw).casefold()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dhash(image, hash_size: int = 8) -> int:
    """A minimal difference-hash (dHash) implemented directly on Pillow,
    with no numpy/scipy dependency. Deliberately not the fuller
    `imagehash` package (phash/wavelet-hash), which pulls in
    numpy+scipy+PyWavelets (~55MB) purely for a DCT/wavelet transform --
    unnecessary weight for a defense-in-depth, staged-comparison signal
    that already falls back to "uncertain" whenever it's not confident.
    Returns a 64-bit integer; Hamming distance between two dHashes is a
    cheap, reasonable proxy for visual similarity.
    """

    small = image.convert("L").resize((hash_size + 1, hash_size), resample=1)
    pixels = list(small.getdata())
    bits = 0
    for row in range(hash_size):
        row_offset = row * (hash_size + 1)
        for col in range(hash_size):
            bits <<= 1
            if pixels[row_offset + col] < pixels[row_offset + col + 1]:
                bits |= 1
    return bits


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _average_color(image) -> tuple[float, float, float]:
    """Mean (R, G, B), 0-255 each. See EmbeddedImageSignal.average_color's
    docstring for why this is needed alongside the gradient-based dHash.
    """

    rgb_image = image.convert("RGB")
    pixels = list(rgb_image.getdata())
    if not pixels:
        return (0.0, 0.0, 0.0)
    n = len(pixels)
    r = sum(p[0] for p in pixels) / n
    g = sum(p[1] for p in pixels) / n
    b = sum(p[2] for p in pixels) / n
    return (r, g, b)


def _classify_image_blank(image) -> bool:
    """Conservative check for whether a decoded raster image is itself
    blank (e.g. a scanned blank sheet). See the threshold constants'
    docstring above for why this uses a dark-pixel ratio rather than a
    single global near-white-ratio/variance pair: a small faint mark
    (signature stroke, stamp corner, barcode) covers such a tiny share
    of a full page's pixels that page-wide statistics alone wash it out.
    """

    gray = image.convert("L")
    pixels = list(gray.getdata())
    if not pixels:
        return True
    total = len(pixels)
    dark_count = sum(1 for p in pixels if p < _BLANK_IMAGE_DARK_LEVEL)
    if (dark_count / total) > _BLANK_IMAGE_MAX_DARK_PIXEL_RATIO:
        return False
    mean = sum(pixels) / total
    variance = sum((p - mean) ** 2 for p in pixels) / total
    return variance <= _BLANK_IMAGE_MAX_VARIANCE


def _extract_embedded_images(page) -> tuple[EmbeddedImageSignal, ...]:
    signals: list[EmbeddedImageSignal] = []
    try:
        image_iter = list(page.images)
    except Exception:
        return ()
    for image_file in image_iter:
        try:
            data = image_file.data
            byte_hash = hashlib.sha256(data).hexdigest()
            pil_image = image_file.image
            width, height = pil_image.size
            phash = _dhash(pil_image) if width > 1 and height > 1 else None
            avg_color = _average_color(pil_image) if width >= 1 and height >= 1 else None
            is_blank = _classify_image_blank(pil_image) if width > 1 and height > 1 else False
            signals.append(
                EmbeddedImageSignal(
                    byte_sha256=byte_hash,
                    perceptual_hash=phash,
                    average_color=avg_color,
                    is_blank=is_blank,
                    width=width,
                    height=height,
                )
            )
        except Exception:
            # A single unreadable embedded image object must never crash
            # fingerprinting for the whole document -- record nothing for
            # it (conservatively, this means it cannot contribute to a
            # blank classification either way, which biases toward
            # "not blank" downstream, the safe direction).
            continue
    return tuple(signals)


def _walk_field_name(annot_dict) -> str:
    """A Widget annotation's own /T may be a partial name; the fully
    qualified field name is built by walking /Parent up to the root,
    joining with '.' -- this is standard AcroForm structure.
    """

    parts: list[str] = []
    seen_ids: set[int] = set()
    current = annot_dict
    for _ in range(32):  # hard cap against a malformed circular /Parent chain
        if current is None:
            break
        obj_id = id(current)
        if obj_id in seen_ids:
            break
        seen_ids.add(obj_id)
        name = current.get("/T")
        if name is not None:
            parts.append(str(name))
        parent = current.get("/Parent")
        if parent is None:
            break
        current = parent.get_object() if isinstance(parent, IndirectObject) else parent
    return ".".join(reversed(parts))


def _extract_page_annotations(
    page,
) -> tuple[tuple[FormFieldSignal, ...], tuple[AnnotationSignal, ...], bool, bool]:
    """Single pass over a page's /Annots: separates Widget (form-field)
    annotations from everything else, and detects signature-field
    presence/signedness. Page-scoped deliberately -- `PdfReader.get_fields()`
    is document-scoped and was flagged during design review as unverified
    for per-page attribution, so annotations are walked directly instead.
    """

    form_fields: list[FormFieldSignal] = []
    annotations: list[AnnotationSignal] = []
    has_signature_field = False
    has_signed_signature = False

    annots = page.get("/Annots")
    if annots is None:
        return (), (), False, False

    for ref in annots:
        try:
            annot = ref.get_object() if isinstance(ref, IndirectObject) else ref
        except Exception:
            continue
        subtype = annot.get("/Subtype")
        subtype_str = str(subtype) if subtype is not None else None

        if subtype_str == "/Widget":
            field_type = annot.get("/FT")
            # /FT can live on this widget or be inherited from /Parent.
            parent = annot
            hops = 0
            while field_type is None and parent.get("/Parent") is not None and hops < 32:
                parent_ref = parent.get("/Parent")
                parent = parent_ref.get_object() if isinstance(parent_ref, IndirectObject) else parent_ref
                field_type = parent.get("/FT")
                hops += 1
            field_type_str = str(field_type) if field_type is not None else None
            value = annot.get("/V")
            value_str = str(value) if value is not None else None
            name = _walk_field_name(annot) or "(unnamed)"
            form_fields.append(FormFieldSignal(name=name, field_type=field_type_str, value=value_str))
            if field_type_str == "/Sig":
                has_signature_field = True
                if value is not None:
                    has_signed_signature = True
        else:
            contents = annot.get("/Contents")
            contents_str = str(contents) if contents is not None else None
            has_ap = "/AP" in annot
            annotations.append(
                AnnotationSignal(
                    subtype=subtype_str,
                    contents=contents_str,
                    has_appearance_stream=has_ap,
                )
            )

    return tuple(form_fields), tuple(annotations), has_signature_field, has_signed_signature


def classify_blank_page(
    normalized_text: str,
    form_fields: tuple[FormFieldSignal, ...],
    annotations: tuple[AnnotationSignal, ...],
    images: tuple[EmbeddedImageSignal, ...],
) -> BlankClassification:
    """Conservative blank-page classification. Blank requires ALL of:
    no meaningful text, no form fields, no annotations with contents or
    an appearance stream, and every embedded image (if any) independently
    classified blank. Any single signal breaking this makes the page
    NOT blank -- ambiguity always resolves to "keep."
    """

    if len(normalized_text) > _BLANK_MAX_TEXT_CHARS:
        return BlankClassification(False, 1.0, f"page has {len(normalized_text)} chars of text")
    if form_fields:
        return BlankClassification(False, 1.0, f"page has {len(form_fields)} form field(s)")
    for annot in annotations:
        if annot.contents or annot.has_appearance_stream:
            return BlankClassification(False, 1.0, f"page has a meaningful {annot.subtype} annotation")
    if images:
        non_blank_images = [img for img in images if not img.is_blank]
        if non_blank_images:
            return BlankClassification(
                False, 1.0, f"page has {len(non_blank_images)} non-blank embedded image(s)"
            )
        # Every embedded image classified blank (e.g. a uniformly white
        # scanned sheet) -- still blank overall, but with slightly lower
        # confidence than the "nothing at all on the page" case, since
        # image-blankness classification is itself a heuristic.
        return BlankClassification(True, 0.9, "no text/fields/meaningful annotations; embedded image(s) blank")
    return BlankClassification(True, 1.0, "no text, form fields, annotations, or images")


def extract_page_fingerprint(reader: PdfReader, page_index: int) -> PageFingerprint:
    page = reader.pages[page_index]

    try:
        raw_text = page.extract_text() or ""
    except Exception:
        raw_text = ""
    case_preserved_text = _collapse_whitespace(raw_text)
    normalized_text = case_preserved_text.casefold()

    try:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
    except Exception:
        width, height = 0.0, 0.0
    rotation = int(page.rotation) if page.rotation else 0

    form_fields, annotations, has_sig_field, has_signed_sig = _extract_page_annotations(page)
    images = _extract_embedded_images(page)
    # Case-preserved text, not the casefolded copy -- the name-hint
    # heuristic depends on capitalization.
    structured = extract_structured_tokens(case_preserved_text)
    blank = classify_blank_page(normalized_text, form_fields, annotations, images)

    return PageFingerprint(
        page_index=page_index,
        normalized_text=normalized_text,
        text_hash=_sha256_text(normalized_text),
        width=width,
        height=height,
        rotation=rotation,
        form_fields=form_fields,
        annotations=annotations,
        has_signature_field=has_sig_field,
        has_signed_signature=has_signed_sig,
        images=images,
        structured_tokens=structured,
        blank=blank,
    )


def build_document_fingerprint(document_id: str, pdf_path) -> DocumentFingerprint:
    reader = PdfReader(str(pdf_path))
    pages = tuple(extract_page_fingerprint(reader, i) for i in range(len(reader.pages)))

    doc_hash_input = "|".join(p.text_hash for p in pages)
    normalized_document_hash = _sha256_text(doc_hash_input)
    has_signature_field = any(p.has_signature_field for p in pages)
    has_form_fields = any(p.form_fields for p in pages)
    if pages:
        page_dims_signature = (round(pages[0].width, 1), round(pages[0].height, 1))
    else:
        page_dims_signature = (0.0, 0.0)

    return DocumentFingerprint(
        document_id=document_id,
        pages=pages,
        normalized_document_hash=normalized_document_hash,
        has_signature_field=has_signature_field,
        has_form_fields=has_form_fields,
        page_dims_signature=page_dims_signature,
    )
