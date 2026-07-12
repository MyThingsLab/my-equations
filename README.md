# my-equations

[![CI](https://github.com/MyThingsLab/my-equations/actions/workflows/ci.yml/badge.svg)](https://github.com/MyThingsLab/my-equations/actions/workflows/ci.yml) [![codecov](https://codecov.io/gh/MyThingsLab/my-equations/branch/main/graph/badge.svg)](https://codecov.io/gh/MyThingsLab/my-equations) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A [MyThingsLab](../my-things-core) `My[X]` tool: extracts every displayed
equation from a PDF into an indexed form — page number, a LaTeX
transcription, and a symbol-by-symbol explanation grounded in the
surrounding prose.

Design doc: [`my-things-core/docs/tools/my-equations.md`](../my-things-core/docs/tools/my-equations.md).
See [`CLAUDE.md`](CLAUDE.md) for the tool's Engine call, invariants, and
backlog label.

```bash
myequations run --engine noop   # or: python -m myequations run
```

is a safe end-to-end dry run: zero tokens, no branch, no PR, one honest
ledger entry.

## Install (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ../my-things-core -e ".[dev]"
pytest
```

## License

MIT — see [`LICENSE`](LICENSE).
