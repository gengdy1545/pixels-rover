#!/usr/bin/env python3
"""Render ``gateway/error-codes.json`` into ``docs/development/backend.md §6.3.1``.

The registry ``gateway/error-codes.json`` is the single source of truth for
infrastructure-prefix error codes (``GATEWAY_*`` / ``INTERNAL_*``).
``backend.md §6.3.1`` is a *rendered view* of that registry — the table
between the ``AUTO-GENERATED-ERROR-CODE-REGISTRY`` markers is rewritten by
this script.

Usage
-----

* Regenerate the table in-place::

      python3 scripts/generate-error-code-registry.py

* Dry-run (no writes, exit non-zero if the rendered output would differ from
  the file on disk — use this as a CI guard in ``scripts/check-contracts.py``
  to catch "JSON was edited but markdown wasn't regenerated")::

      python3 scripts/generate-error-code-registry.py --check

The script deliberately does **not** try to rewrite the prose surrounding
the table. Surrounding prose is authored by hand; only the table body plus
its markdown header row is auto-generated.

Hard rule (backend.md §6.3.1): any manual edit inside the markers is
transient — the next regeneration pass will overwrite it. Fix the JSON
instead.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "gateway" / "error-codes.json"
BACKEND_MD_PATH = REPO_ROOT / "docs" / "development" / "backend.md"

BEGIN_MARKER = "<!-- AUTO-GENERATED-ERROR-CODE-REGISTRY:BEGIN -->"
END_MARKER = "<!-- AUTO-GENERATED-ERROR-CODE-REGISTRY:END -->"

# Column order for the rendered markdown table. Changing this order or the
# header strings is a documentation contract change — update backend.md
# §6.3.1 prose accordingly.
COLUMNS = [
    ("errorCode", "`errorCode`"),
    ("httpStatus", "HTTP"),
    ("category", "`category`"),
    ("writtenBy", "写入方"),
    ("trigger", "触发条件"),
    ("docAnchor", "文档锚点"),
]


def load_registry() -> dict:
    raw = REGISTRY_PATH.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: {REGISTRY_PATH} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(2)

    codes = data.get("codes")
    if not isinstance(codes, dict) or not codes:
        print(
            f"error: {REGISTRY_PATH} is missing a non-empty `codes` object",
            file=sys.stderr,
        )
        sys.exit(2)
    return data


def escape_cell(value: str) -> str:
    """Escape pipes + trim whitespace so a multi-line trigger stays on one row."""
    return value.replace("\n", " ").replace("|", "\\|").strip()


def render_row(code_name: str, meta: dict) -> str:
    cells = []
    for key, _header in COLUMNS:
        if key == "errorCode":
            cells.append(f"`{code_name}`")
        elif key == "httpStatus":
            cells.append(f"`{meta['httpStatus']}`")
        elif key == "category":
            cells.append(f"`{meta['category']}`")
        else:
            cells.append(escape_cell(str(meta[key])))
    return "| " + " | ".join(cells) + " |"


def render_table(codes: dict) -> str:
    header_row = "| " + " | ".join(h for _k, h in COLUMNS) + " |"
    separator = "|" + "|".join(["---"] * len(COLUMNS)) + "|"
    # Stable order: sort by (category, httpStatus, name) to keep related codes
    # adjacent. If the contract ever requires a specific order we can flip this
    # to an explicit `order` list in the JSON.
    ordered = sorted(
        codes.items(),
        key=lambda kv: (kv[1]["category"], kv[1]["httpStatus"], kv[0]),
    )
    lines = [header_row, separator]
    lines.extend(render_row(name, meta) for name, meta in ordered)
    return "\n".join(lines)


def splice(markdown: str, rendered_table: str) -> str:
    begin_idx = markdown.find(BEGIN_MARKER)
    end_idx = markdown.find(END_MARKER)
    if begin_idx == -1 or end_idx == -1 or end_idx < begin_idx:
        print(
            f"error: markers not found or inverted in {BACKEND_MD_PATH}:\n"
            f"       expected both `{BEGIN_MARKER}` and `{END_MARKER}`",
            file=sys.stderr,
        )
        sys.exit(2)

    head = markdown[: begin_idx + len(BEGIN_MARKER)]
    tail = markdown[end_idx:]
    # Surround the generated table with single blank lines so the markers stay
    # visually separated in the source view but the table renders contiguously.
    return f"{head}\n\n{rendered_table}\n\n{tail}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the file on disk would change; do not write",
    )
    args = parser.parse_args()

    registry = load_registry()
    rendered_table = render_table(registry["codes"])

    current = BACKEND_MD_PATH.read_text(encoding="utf-8")
    updated = splice(current, rendered_table)

    if args.check:
        if current != updated:
            print(
                "error: backend.md §6.3.1 is out of sync with gateway/error-codes.json.\n"
                "       Run `python3 scripts/generate-error-code-registry.py` and commit.",
                file=sys.stderr,
            )
            return 1
        return 0

    if current == updated:
        print("backend.md §6.3.1 already up to date.")
        return 0

    BACKEND_MD_PATH.write_text(updated, encoding="utf-8")
    print(f"rewrote {BACKEND_MD_PATH.relative_to(REPO_ROOT)} (§6.3.1 table)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
