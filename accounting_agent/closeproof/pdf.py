"""Small deterministic text-PDF fixture builder and parser.

The parser deliberately supports only the uncompressed, text-only PDF shape
generated here. It is a competition fixture boundary, not a general PDF/OCR
claim.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


class SyntheticPdfError(ValueError):
    """Raised when a PDF is outside the deterministic fixture contract."""


def build_text_pdf(lines: Iterable[str]) -> bytes:
    normalized = tuple(_normalize_line(line) for line in lines)
    if not normalized:
        raise SyntheticPdfError("at least one text line is required")
    if len(normalized) > 36:
        raise SyntheticPdfError("the synthetic PDF supports at most 36 lines")

    commands = [b"BT", b"/F1 11 Tf", b"50 760 Td"]
    for index, line in enumerate(normalized):
        if index:
            commands.append(b"0 -18 Td")
        commands.append(b"(" + _escape_pdf_text(line) + b") Tj")
    commands.append(b"ET")
    stream = b"\n".join(commands) + b"\n"

    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream
        + b"endstream",
    )

    output = bytearray(b"%PDF-1.4\n%CloseProof synthetic fixture\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def extract_fixture_pdf_lines(content: bytes) -> tuple[str, ...]:
    if not isinstance(content, bytes) or not content.startswith(b"%PDF-1.4"):
        raise SyntheticPdfError("expected a CloseProof PDF 1.4 fixture")
    if b"/FlateDecode" in content or b"/Filter" in content:
        raise SyntheticPdfError("compressed or filtered PDFs are unsupported")
    matches = re.findall(rb"\(((?:\\.|[^\\)])*)\)\s+Tj", content)
    if not matches:
        raise SyntheticPdfError("the fixture contains no supported text operators")
    lines = tuple(_unescape_pdf_text(match).decode("latin-1") for match in matches)
    if not lines[0].startswith("SYNTHETIC DEMO DOCUMENT"):
        raise SyntheticPdfError("the PDF is missing the synthetic-data marker")
    return lines


def _normalize_line(value: str) -> bytes:
    if not isinstance(value, str):
        raise TypeError("PDF lines must be strings")
    value = value.strip()
    if not value:
        raise SyntheticPdfError("PDF lines must not be blank")
    if len(value) > 160:
        raise SyntheticPdfError("PDF fixture lines must not exceed 160 characters")
    return value.encode("latin-1", "replace")


def _escape_pdf_text(value: bytes) -> bytes:
    return value.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _unescape_pdf_text(value: bytes) -> bytes:
    result = bytearray()
    index = 0
    while index < len(value):
        byte = value[index]
        if byte == 92 and index + 1 < len(value):
            index += 1
            result.append(value[index])
        else:
            result.append(byte)
        index += 1
    return bytes(result)
