from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from myequations.extract import extract_equations

# The base-14 fonts PyMuPDF defaults to are WinAnsi-encoded and silently
# mangle Greek/math-Unicode glyphs into "."; embed a real Unicode font so
# fixtures exercise the actual glyphs the heuristic looks for.
_UNICODE_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _unicode_page(doc: fitz.Document, **kwargs) -> fitz.Page:
    page = doc.new_page(**kwargs)
    page.insert_font(fontname="F0", fontfile=_UNICODE_FONT)
    return page


def _make_pdf(path: Path, *, equation: str | None = "σ² = E[(x − μ)²]") -> None:
    doc = fitz.open()
    page = _unicode_page(doc, width=400, height=500)
    page.insert_text(
        (50, 50), "Here sigma denotes the standard deviation of the noise term.", fontname="F0"
    )
    if equation is not None:
        page.insert_text((150, 90), equation, fontsize=13, fontname="F0")
    page.insert_text((50, 130), "The mean mu is estimated from the sample above.", fontname="F0")
    doc.save(path)
    doc.close()


@pytest.fixture()
def pdf_with_equation(tmp_path: Path) -> Path:
    path = tmp_path / "doc.pdf"
    _make_pdf(path)
    return path


def test_detects_one_math_unicode_region(pdf_with_equation: Path) -> None:
    regions = extract_equations(pdf_with_equation)
    assert len(regions) == 1
    region = regions[0]
    assert region.page == 1
    assert region.image.startswith(b"\x89PNG")


def test_nearby_text_captures_surrounding_prose(pdf_with_equation: Path) -> None:
    (region,) = extract_equations(pdf_with_equation)
    assert "standard deviation" in region.nearby_text or "mean mu" in region.nearby_text


def test_inline_single_char_variable_is_not_a_region(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = _unicode_page(doc)
    page.insert_text((50, 50), "let x be the noise term, as usual.", fontname="F0")
    doc.save(path)
    doc.close()
    assert extract_equations(path) == []


def test_prose_only_pdf_has_no_regions(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = _unicode_page(doc)
    page.insert_text((50, 50), "just some ordinary prose, nothing mathematical here", fontname="F0")
    doc.save(path)
    doc.close()
    assert extract_equations(path) == []


def test_multi_line_equation_clusters_into_one_region(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = _unicode_page(doc, width=400, height=500)
    page.insert_text((150, 90), "σ² = E[(x − μ)²]", fontsize=13, fontname="F0")
    page.insert_text((150, 105), "= Var(x) − 1", fontsize=13, fontname="F0")
    doc.save(path)
    doc.close()
    regions = extract_equations(path)
    assert len(regions) == 1
