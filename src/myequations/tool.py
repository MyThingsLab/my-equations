from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mythings.engine import Engine, EngineRequest, EngineResult
from mythings.github import GitHub, Issue
from mythings.ledger import Ledger
from mythings.policy import Policy
from mythings.tool import BaseToolRunner
from mythings.tool import ToolRunResult as Result

from myequations.extract import EquationRegion, extract_equations

TOOL = "myequations"
LEDGER_KIND = "equation_extract"
BACKLOG_LABEL = "my-equations"

SYSTEM = (
    "You are given one or more equation regions cropped from a document page, "
    "each preceded by nearby page text for context. For each region, in the "
    "order given, transcribe it to LaTeX and, for each named symbol appearing "
    "in it, give a one-line meaning grounded only in the surrounding prose -- "
    "never invent a meaning that isn't stated nearby; use an empty string "
    'instead. Reply with strict JSON: {"equations": [{"latex": str, '
    '"symbols": [{"symbol": str, "meaning": str}]}, ...]}, one entry per '
    "region, same order."
)

_SOURCE_RE = re.compile(r"^\s*eq-source:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(stem: str) -> str:
    return _SLUG_RE.sub("-", stem.lower()).strip("-") or "doc"


def _parse_source(body: str) -> str | None:
    match = _SOURCE_RE.search(body)
    return match.group(1) if match else None


def _run_git(tree: Path, argv: list[str]) -> None:
    proc = subprocess.run(["git", *argv], cwd=tree, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(argv)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )


@dataclass(frozen=True)
class Symbol:
    symbol: str
    meaning: str


def _render_index(
    doc_id: str, regions: list[EquationRegion], transcriptions: list[tuple[str, list[Symbol]]]
) -> str:
    rows = []
    for n, (region, (latex, symbols)) in enumerate(zip(regions, transcriptions, strict=True), 1):
        rows.append(
            {
                "page": region.page,
                "bbox": list(region.bbox),
                "latex": latex,
                "symbols": [{"symbol": s.symbol, "meaning": s.meaning} for s in symbols],
                "image": f"p{region.page}-{n}.png",
            }
        )
    return json.dumps({"doc_id": doc_id, "equations": rows}, indent=2, sort_keys=True) + "\n"


def _render_readme(
    doc_id: str, regions: list[EquationRegion], transcriptions: list[tuple[str, list[Symbol]]]
) -> str:
    lines = [f"# Equations — {doc_id}", ""]
    for n, (region, (latex, symbols)) in enumerate(zip(regions, transcriptions, strict=True), 1):
        lines.append(f"## p{region.page}-{n}.png (page {region.page})")
        lines.append("")
        lines.append("```math")
        lines.append(latex or "(untranscribed)")
        lines.append("```")
        lines.append("")
        if symbols:
            lines.append("| symbol | meaning |")
            lines.append("| --- | --- |")
            for s in symbols:
                lines.append(f"| {s.symbol} | {s.meaning} |")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class Tool(BaseToolRunner):
    def __init__(
        self,
        *,
        repo: str | Path = ".",
        ledger: Ledger | None = None,
        github: GitHub | None = None,
        engine: Engine | None = None,
        policy: Policy | None = None,
        base: str = "main",
        label: str = BACKLOG_LABEL,
        git: Callable[[Path, list[str]], None] | None = None,
        extractor: Callable[[Path], list[EquationRegion]] = extract_equations,
    ) -> None:
        super().__init__(
            repo=repo,
            ledger=ledger,
            github=github,
            engine=engine,
            policy=policy,
            base=base,
            label=label,
            git=git,
        )
        self._extractor = extractor
        self._doc_id = ""
        self._regions: list[EquationRegion] = []

    def prework(self, issue: Issue) -> str:
        source = _parse_source(issue.body)
        if source is None:
            return "no eq-source: locator in issue body"

        path = Path(source)
        if not path.is_file():
            return f"eq-source path does not exist: {source}"

        self._doc_id = _slug(path.stem)
        self._regions = self._extractor(path)
        return f"{len(self._regions)} equation region(s) detected"

    def request(self, issue: Issue, context: str) -> EngineRequest:
        if not self._regions:
            return EngineRequest(prompt="nothing to transcribe", system=SYSTEM)

        lines = [f"{len(self._regions)} region(s), in order:"]
        for n, region in enumerate(self._regions, start=1):
            lines.append(f"{n}. page {region.page}. Nearby text: {region.nearby_text}")
        return EngineRequest(
            prompt="\n".join(lines),
            system=SYSTEM,
            images=tuple(region.image for region in self._regions),
        )

    def apply(self, tree: Path, issue: Issue, result: EngineResult) -> str | None:
        if not self._regions:
            return None

        parsed = self._parse_equations(result.text)
        transcriptions: list[tuple[str, list[Symbol]]] = []
        for n in range(len(self._regions)):
            if n < len(parsed):
                transcriptions.append(parsed[n])
            else:
                transcriptions.append(("", []))

        out_dir = tree / "equations" / self._doc_id
        out_dir.mkdir(parents=True, exist_ok=True)
        for n, region in enumerate(self._regions, start=1):
            (out_dir / f"p{region.page}-{n}.png").write_bytes(region.image)
        (out_dir / "index.json").write_text(
            _render_index(self._doc_id, self._regions, transcriptions), encoding="utf-8"
        )
        (out_dir / "README.md").write_text(
            _render_readme(self._doc_id, self._regions, transcriptions), encoding="utf-8"
        )
        return f"equations/{self._doc_id}"

    @staticmethod
    def _parse_equations(text: str) -> list[tuple[str, list[Symbol]]]:
        if not text:
            return []
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return []
        equations = obj.get("equations")
        if not isinstance(equations, list):
            return []
        parsed: list[tuple[str, list[Symbol]]] = []
        for entry in equations:
            if not isinstance(entry, dict):
                parsed.append(("", []))
                continue
            latex = str(entry.get("latex") or "")
            symbols_raw = entry.get("symbols")
            symbols: list[Symbol] = []
            if isinstance(symbols_raw, list):
                for sym in symbols_raw:
                    if isinstance(sym, dict):
                        symbols.append(
                            Symbol(
                                symbol=str(sym.get("symbol") or ""),
                                meaning=str(sym.get("meaning") or ""),
                            )
                        )
            parsed.append((latex, symbols))
        return parsed

    def run(self, issue_number: int | None = None) -> Result:
        return self.run_issue_workflow(TOOL, LEDGER_KIND, issue_number)
