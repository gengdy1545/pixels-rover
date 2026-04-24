#!/usr/bin/env python3
"""Render .env.example from config/required-env.yaml.

This is the SSOT enforcement lever for §14 — operators never
hand-edit .env.example. Instead:

  1. Change config/required-env.yaml.
  2. Run `python3 scripts/generate-env-example.py`.
  3. Commit the regenerated .env.example alongside the YAML edit.

scripts/check-contracts.py's `env-example-matches-required-env-yaml`
asserts byte-identical re-render at PR gate time, so forgetting step 2
fails CI loudly.

Output layout (see .env.example header):

  * One `# ==== <service> ====` banner per service block.
  * One paragraph per variable. Paragraph shape:

      # <first-line-of-description-reflowed-to-72-cols>
      # <constraint summary — enum / required_when / forbidden_values etc>
      KEY=<value-or-placeholder>

    Sensitive vars render as `KEY=` (empty) with an explicit
    `# REQUIRED: supply before first boot` line so a grep for `=` alone
    can count unresolved secrets.

  * No colours. No emoji. Plain stdout; the operator redirects into
    .env.example themselves when editing, but the script writes the
    file in place by default for ergonomics.
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:
    print("error: PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YAML = REPO_ROOT / "config" / "required-env.yaml"
DEFAULT_OUT = REPO_ROOT / ".env.example"


HEADER = """\
# Pixels Rover — Docker Compose Environment Variables
#
# This file is AUTO-GENERATED from config/required-env.yaml by
# scripts/generate-env-example.py. Do NOT hand-edit — your change will
# be overwritten the next time the generator runs, and the PR-gate
# contract check `env-example-matches-required-env-yaml` will fail.
#
# Workflow to add / modify an env var:
#   1. Edit config/required-env.yaml (the single source of truth).
#   2. Run: python3 scripts/generate-env-example.py
#   3. Commit both files in the same PR.
#
# Layout:
#   * Required block — one banner per service / deployment component. Each
#     var has its description, constraints, and assignment line;
#     `sensitive: true` entries render as `KEY=` (empty) — you MUST fill
#     them in your local .env before `docker compose up`.
#   * Optional block (footer) — commonly-tuned knobs that docker-compose.yml
#     already carries sensible defaults for. Listed here for operator
#     convenience; safe to leave unset.
#
# See docs/development/backend.md §13 for the "FATAL-on-missing" rule
# that each service's RequiredEnvValidator implements.
"""


# Non-required knobs. These have `:-<default>` fallbacks in
# docker-compose.yml today; listing them here is purely an operator UX
# affordance. They are NOT consumed by any RequiredEnvValidator, and
# check-contracts.py does not walk this block.
FOOTER = """\

# ==== Optional (docker-compose.yml carries defaults) ====

# LLM provider knobs (also see ROVER_LLM_API_KEY above — that one is required).
# LLM_MODEL=gpt-4o-mini
# LLM_API_BASE=https://api.openai.com/v1

# MySQL root + app passwords and port. The app user is created by
# db/pixels_rover.sql (initdb.d, first-boot only).
# MYSQL_ROOT_PASSWORD=rootpassword
# MYSQL_PASSWORD=password
# MYSQL_PORT=3306

# External port the API gateway (APISIX) listens on. All traffic enters
# here; backend services are not directly exposed.
# GATEWAY_PORT=80

# Pixels-server (used by assistant-service when querying Pixels-backed schemas).
# PIXELS_HOST=host.docker.internal
# PIXELS_PORT=18890

# Assistant-service debug toggle. Keep this project-scoped instead of DEBUG to
# avoid colliding with shell/debugger-provided DEBUG values.
# ROVER_DEBUG=false

# DuckDB storage path. The compose default is persistent and mounted on the
# assistant-duckdb named volume. Set ROVER_DUCKDB_PATH=:memory: for throwaway
# local demos/tests; that mode loses analysis data on restart.
# ROVER_DUCKDB_PATH=/var/lib/pixels-rover/duckdb/analysis.duckdb

# ==== Optional frontend build-time overrides ====

# Vite-time override for the frontend's axios + SSE baseURL. Unset
# preserves same-origin behaviour (the bundle's host becomes the API
# host), which is what production ships. Local dev against a remote
# gateway (or a future non-browser client pointing at a specific host)
# sets this at build time, e.g. `VITE_API_BASE=http://localhost:9080`.
# See frontend/src/shared/api/client.ts#resolveApiUrl.
# VITE_API_BASE=
"""


def _wrap_description(text: str, prefix: str = "# ") -> list[str]:
    """Collapse whitespace + wrap to 72 cols with ``prefix``."""
    collapsed = " ".join(text.split())
    return textwrap.wrap(
        collapsed,
        width=72,
        initial_indent=prefix,
        subsequent_indent=prefix,
    ) or [prefix.rstrip()]


def _constraint_summary(entry: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if entry.get("required"):
        lines.append("# REQUIRED (always)")
    if "required_when" in entry:
        lines.append(f"# REQUIRED when {entry['required_when']}")
    if "forbidden_when" in entry:
        lines.append(f"# MUST BE UNSET when {entry['forbidden_when']}")
    if "enum" in entry:
        lines.append(f"# ALLOWED VALUES: {', '.join(entry['enum'])}")
    if "forbidden_values" in entry:
        lines.append(
            f"# FORBIDDEN VALUES: {', '.join(repr(v) for v in entry['forbidden_values'])}"
        )
    if "min_utf8_bytes" in entry:
        lines.append(f"# MINIMUM LENGTH: {entry['min_utf8_bytes']} UTF-8 bytes")
    if entry.get("file_must_exist"):
        lines.append("# MUST be a readable file path at container-start time")
    if entry.get("sensitive"):
        lines.append("# SENSITIVE — supply before first boot; never commit a real value")
    return lines


def _render_value(entry: dict[str, Any]) -> str:
    if "env_example" in entry:
        return f"{entry['name']}={entry['env_example']}"
    if entry.get("sensitive"):
        return f"{entry['name']}="
    if "enum" in entry and entry["enum"]:
        return f"{entry['name']}={entry['enum'][0]}"
    return f"{entry['name']}="


def render(doc: dict[str, Any]) -> str:
    out: list[str] = [HEADER]
    services = doc.get("services") or {}
    for svc_name, entries in services.items():
        out.append("")
        out.append(f"# ==== {svc_name} ====")
        for entry in entries:
            out.append("")
            out.extend(_wrap_description(entry["description"]))
            out.extend(_constraint_summary(entry))
            out.append(_render_value(entry))
    out.append(FOOTER.rstrip("\n"))
    # Trailing newline for POSIX-friendly diffs.
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yaml", default=str(DEFAULT_YAML), help="path to required-env.yaml")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output path for .env.example")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if --out would change (used by check-contracts)",
    )
    args = parser.parse_args()

    with open(args.yaml, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    rendered = render(doc)

    out_path = Path(args.out)
    if args.check:
        existing = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        if existing != rendered:
            print(
                f"error: {out_path} is out of sync with {args.yaml}; "
                "re-run scripts/generate-env-example.py",
                file=sys.stderr,
            )
            return 1
        return 0

    out_path.write_text(rendered, encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
