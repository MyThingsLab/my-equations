# my-equations — agent instructions

You are developing **my-equations**, a MyThingsLab My[X] tool.

**Inherited rules:** obey [`./HARNESS.md`](./HARNESS.md) in full — the vendored
MyThingsLab build-harness rules. Do not restate or override them. Anything not
covered here defers to `HARNESS.md`, then `my-things-core/docs/CONVENTIONS.md`.

## This tool

- **Purpose:** extracts every displayed equation from a PDF into an indexed
  form — page number, a LaTeX transcription, and a symbol-by-symbol
  explanation grounded in the surrounding prose — see the design doc:
  [`my-things-core/docs/tools/my-equations.md`](../my-things-core/docs/tools/my-equations.md).
- **The single Engine call:** required (batched per document, still exactly
  one call per run) — "given this equation region (image) and the
  surrounding page text, transcribe it to LaTeX and, for each named symbol,
  give a one-line meaning grounded in the surrounding prose." There is no
  deterministic math-to-LaTeX path, unlike MyFigure/MyTables' optional
  caption-gap call. A symbol with no stated meaning nearby gets
  `meaning=""`, never an invented definition. Against `NoopEngine`, regions
  are still indexed with `latex=""`, `symbols=[]`.
- **Invariants / rules:** deterministic pre-work only locates candidate
  regions (open the PDF with `PyMuPDF`, flag math-typeset-font spans,
  cluster adjacent spans, discard single-character inline-variable hits,
  crop each region to an image) — it never attempts transcription itself.
  `PyMuPDF` is this tool's own runtime dependency, not core's (core stays
  dependency-free). Triggered by an open `my-equations`-labeled issue
  (`eq-source:<path>`), the same handoff shape MyArchivist already uses for
  MyBibliography — never a direct call into or import of MyArchivist.
  Writes `equations/<doc-id>/` (region crops + `index.json` + a rendered
  README) inside a `Workspace` and opens exactly one PR per run, routed
  through `Policy` (`Guard` default). **Never merges.** Ledger `kind`:
  `equation_extract`.
- **Backlog label:** `my-equations`

## Testing

Fakes come from `mythings.testing` (opt-in via `pytest_plugins` in
`tests/conftest.py`; see `my-things-core/docs/CONVENTIONS.md`, "Shared test
fixtures"). Never copy fixture code into a conftest — only domain-specific
helpers live there.
