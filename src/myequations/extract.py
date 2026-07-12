from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz

# Math-typeset font families (the Computer Modern family LaTeX emits, plus
# generic "Symbol") -- a strong signal on its own. See
# my-things-core/docs/tools/my-equations.md, "Deterministic pre-work".
_MATH_FONT_RE = re.compile(r"cmmi|cmsy|cmex|cmbx|cmr\d|symbol", re.IGNORECASE)

# Greek letters, math operators/relations, and sub/superscript digits --
# common in math-Unicode text even without an embedded math font.
_MATH_CHAR_RE = re.compile(r"[Ͱ-Ͽ∀-⋿⁰-₟]")

# Fraction of a (stripped) line's characters that must look like math, when
# the font-name signal alone doesn't already flag the line.
_MATH_CHAR_RATIO = 0.15

# Vertical gap (PDF points) within which two flagged lines are treated as one
# multi-line equation region rather than two separate ones.
_CLUSTER_GAP = 6.0

# Padding (PDF points) added around a clustered region's bounding box before
# cropping -- keeps thin math glyphs (integral signs, fraction bars) from
# being clipped at the edge.
_CROP_PADDING = 4.0

# Number of characters of page text to capture on either side of a region
# for symbol-grounding context.
_NEARBY_CHARS = 300


@dataclass(frozen=True)
class EquationRegion:
    page: int  # 1-indexed, matching how a human would cite the page
    bbox: tuple[float, float, float, float]
    image: bytes  # PNG-encoded crop
    nearby_text: str  # page prose immediately before/after, for symbol grounding


def _is_math_line(text: str, font: str) -> bool:
    stripped = text.strip()
    if len(stripped) <= 1:
        return False  # a lone italic variable inline in prose, not a displayed equation
    if _MATH_FONT_RE.search(font):
        return True
    math_chars = len(_MATH_CHAR_RE.findall(stripped))
    return (math_chars / len(stripped)) >= _MATH_CHAR_RATIO


def _line_spans(page: fitz.Page) -> list[dict]:
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s["text"] for s in spans)
            font = spans[0].get("font", "")
            x0 = min(s["bbox"][0] for s in spans)
            y0 = min(s["bbox"][1] for s in spans)
            x1 = max(s["bbox"][2] for s in spans)
            y1 = max(s["bbox"][3] for s in spans)
            lines.append({"text": text, "font": font, "bbox": (x0, y0, x1, y1)})
    return lines


def _cluster(flagged: list[dict]) -> list[list[dict]]:
    clusters: list[list[dict]] = []
    for line in sorted(flagged, key=lambda ln: ln["bbox"][1]):
        if clusters and (line["bbox"][1] - clusters[-1][-1]["bbox"][3]) <= _CLUSTER_GAP:
            clusters[-1].append(line)
        else:
            clusters.append([line])
    return clusters


def _nearby_text(all_text: str, region_text: str) -> str:
    idx = all_text.find(region_text)
    if idx == -1:
        return all_text[:_NEARBY_CHARS]
    before = all_text[max(0, idx - _NEARBY_CHARS) : idx]
    after = all_text[idx + len(region_text) : idx + len(region_text) + _NEARBY_CHARS]
    return (before + after).strip()


def extract_equations(pdf_path: Path) -> list[EquationRegion]:
    doc = fitz.open(pdf_path)
    try:
        regions: list[EquationRegion] = []
        for page_index in range(doc.page_count):
            page = doc[page_index]
            lines = _line_spans(page)
            flagged = [line for line in lines if _is_math_line(line["text"], line["font"])]
            page_text = page.get_text()

            for cluster in _cluster(flagged):
                combined = "".join(line["text"] for line in cluster).strip()
                if len(combined) <= 1:
                    continue  # a cluster of one single-character span
                x0 = min(line["bbox"][0] for line in cluster) - _CROP_PADDING
                y0 = min(line["bbox"][1] for line in cluster) - _CROP_PADDING
                x1 = max(line["bbox"][2] for line in cluster) + _CROP_PADDING
                y1 = max(line["bbox"][3] for line in cluster) + _CROP_PADDING
                rect = fitz.Rect(x0, y0, x1, y1) & page.rect
                pixmap = page.get_pixmap(clip=rect)
                region_text = "\n".join(line["text"] for line in cluster)
                regions.append(
                    EquationRegion(
                        page=page_index + 1,
                        bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                        image=pixmap.tobytes("png"),
                        nearby_text=_nearby_text(page_text, region_text),
                    )
                )
        return regions
    finally:
        doc.close()
