#!/usr/bin/env python3
"""Deterministic OpenAPI snapshot exporter for ``assistant-service``.

The frontend's auto-generated TypeScript types
(``frontend/src/shared/types/generated/assistant.d.ts``) are rendered by
``openapi-typescript`` off a committed JSON snapshot rather than a live
``/openapi.json`` fetch. Two reasons:

  1. CI determinism — running backends in a frontend-only job is overkill,
     and HTTP scraping introduces clock / network noise that would mask
     real schema drift.
  2. Review surface — the snapshot is a plain ``.json`` file in the tree;
     a PR that changes a pydantic field shows up as a diff here, so the
     contract change is visible to code reviewers even before CI runs.

This script renders the snapshot to ``services/assistant-service/openapi.json``
in a byte-identical way across runs:

  * ``sort_keys=True`` so dict iteration order cannot flake the output.
  * ``indent=2`` and a trailing ``\\n`` so Git line-diffs are clean.
  * ``ensure_ascii=False`` so Chinese descriptions in pydantic ``Field``
    annotations render as their native characters (matches the default
    FastAPI web rendering).

Cross-layer contract:
  * ``scripts/check-contracts.py`` asserts that re-running this script
    produces no diff against the committed file; a missing run fails CI
    before ``openapi-typescript`` is invoked.
  * ``frontend/package.json`` ``gen:types`` consumes the same file via
    ``openapi-typescript``; CI asserts that re-running ``gen:types``
    also produces no diff against the committed ``assistant.d.ts``.

Usage:
    python3 scripts/export-openapi.py              # prints planned path, rewrites snapshot
    python3 scripts/export-openapi.py --check      # non-zero exit iff snapshot stale
    python3 scripts/export-openapi.py --stdout     # emit JSON to stdout, no file write

Environment knobs (set by this script automatically when not already set):
    ROVER_REQUIRED_ENV_SKIP=1   — bypass §14 env-var hard validator
                                   (OpenAPI rendering has no runtime deps)
    ROVER_LLM_API_KEY=dummy     — some pydantic defaults may be evaluated
                                   during FastAPI app construction
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICE_ROOT = REPO_ROOT / "services" / "assistant-service"
SNAPSHOT_PATH = SERVICE_ROOT / "openapi.json"


def _prepare_environment() -> None:
    """Set the minimum env vars required so ``create_app()`` returns without
    performing any I/O or connecting to MySQL / DuckDB.

    ``app.main.create_app`` runs the §14 env validator before constructing
    the FastAPI instance. For a pure-schema export we skip it; in return we
    never touch the validator itself, so this script deliberately does NOT
    silence validation errors in ANY other code path.
    """
    os.environ.setdefault("ROVER_REQUIRED_ENV_SKIP", "1")
    # The settings object pulls these at import time; providing any
    # non-empty value is enough to satisfy pydantic validators that
    # run during ``FastAPI(...)`` construction. They are NEVER exercised
    # because no route is actually served.
    os.environ.setdefault("ROVER_LLM_API_KEY", "dummy-openapi-export-key")
    os.environ.setdefault("ROVER_DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def _build_openapi_document() -> dict:
    """Import ``app.main`` and return the OpenAPI document.

    The import happens here (not at module top) so that environment
    preparation is completed first. ``app.main`` is only importable with
    ``services/assistant-service`` on ``sys.path``.
    """
    sys.path.insert(0, str(SERVICE_ROOT))
    try:
        from app.main import app  # type: ignore[import-not-found]
    finally:
        # Restore sys.path so any consumer of this module doesn't inherit
        # the injected service root. The app instance itself is cached by
        # FastAPI, so re-imports stay cheap.
        sys.path.pop(0)
    return app.openapi()


def _render_snapshot(document: dict) -> str:
    """Render ``document`` deterministically.

    Contract: every byte here must be reproducible from the pydantic
    schemas alone — no timestamps, no ``uuid`` generation, no locale-
    dependent formatting. ``sort_keys=True`` is non-negotiable.
    """
    return json.dumps(
        document,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Render assistant-service OpenAPI snapshot."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help=(
            "Exit non-zero iff the committed snapshot differs from the "
            "freshly rendered document. Does NOT rewrite the file."
        ),
    )
    mode.add_argument(
        "--stdout",
        action="store_true",
        help="Write rendered JSON to stdout instead of the snapshot file.",
    )
    args = parser.parse_args(argv)

    _prepare_environment()
    document = _build_openapi_document()
    rendered = _render_snapshot(document)

    if args.stdout:
        sys.stdout.write(rendered)
        return 0

    if args.check:
        if not SNAPSHOT_PATH.is_file():
            print(
                f"FAIL: snapshot missing at {SNAPSHOT_PATH.relative_to(REPO_ROOT)}; "
                "run scripts/export-openapi.py to create it.",
                file=sys.stderr,
            )
            return 1
        on_disk = SNAPSHOT_PATH.read_text(encoding="utf-8")
        if on_disk != rendered:
            print(
                "FAIL: OpenAPI snapshot is stale; re-run "
                "`python3 scripts/export-openapi.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        return 0

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {SNAPSHOT_PATH.relative_to(REPO_ROOT)} ({len(rendered)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
