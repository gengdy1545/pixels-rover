"""§14 hard-validation of required environment variables.

Contract mirror of gateway/validate-required-env.py and
io.pixelsdb.pixels.rover.bootstrap.RequiredEnvValidator — all three
read the same config/required-env.yaml SSOT. scripts/check-contracts.py
asserts that this module, the gateway validator, the Java validator,
scripts/generate-env-example.py, and scripts/smoke.sh all reference
the same YAML path pattern.

Invocation site: ``create_app()`` in app.main calls
``validate_or_die()`` BEFORE the FastAPI instance is returned, so a
violation causes the process to exit before uvicorn binds :8090 — no
half-ready state ever reaches /gateway/ready aggregation.

Tests can bypass by setting ``ROVER_REQUIRED_ENV_SKIP=1``. Production
compose must never set that variable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml


SERVICE_NAME = "assistant-service"
DEFAULT_YAML_PATH = "/app/config/required-env.yaml"


def _fatal(msg: str) -> None:
    print(f"FATAL assistant-service/required-env: {msg}", file=sys.stderr, flush=True)


def _value_for(name: str) -> str:
    return os.environ.get(name, "")


def _validate_entry(entry: dict[str, Any], failures: list[str]) -> None:
    name = entry["name"]
    value = _value_for(name)

    required = entry.get("required", False)
    required_when = entry.get("required_when")
    forbidden_when = entry.get("forbidden_when")

    other_matches: bool | None = None
    clause = required_when or forbidden_when
    if clause:
        if "=" not in clause:
            failures.append(
                f"{name}: malformed required_when/forbidden_when clause "
                f"{clause!r}; expected OTHER=value"
            )
            return
        other_name, expected = clause.split("=", 1)
        other_matches = _value_for(other_name) == expected

    is_required = required or (required_when is not None and other_matches)
    is_forbidden = forbidden_when is not None and other_matches

    if is_forbidden and value:
        failures.append(
            f"{name} MUST be unset because {forbidden_when} (mutually "
            f"exclusive group). Got {value!r}."
        )
        return

    if not value:
        if is_required:
            why = "unconditional" if required else f"because {required_when}"
            failures.append(
                f"{name} is required ({why}) but is empty or unset. "
                f"See config/required-env.yaml for description."
            )
        return

    if "enum" in entry and value not in entry["enum"]:
        failures.append(
            f"{name}={value!r} is not in allowed enum {entry['enum']} "
            f"(strict string match)."
        )
    for bad in entry.get("forbidden_values", []):
        if value == bad:
            failures.append(
                f"{name}={value!r} matches forbidden placeholder {bad!r}; "
                f"refusing to boot."
            )
    if "min_utf8_bytes" in entry:
        actual = len(value.encode("utf-8"))
        if actual < entry["min_utf8_bytes"]:
            failures.append(
                f"{name} is {actual} UTF-8 bytes, below minimum "
                f"{entry['min_utf8_bytes']}."
            )
    if entry.get("file_must_exist"):
        p = Path(value)
        if not p.is_file():
            failures.append(
                f"{name}={value!r} is not a regular file (check compose volume)."
            )


def validate_or_die(yaml_path: str | None = None) -> None:
    """Validate the assistant-service block or exit non-zero.

    Returns normally on success. On any violation emits FATAL lines to
    stderr and calls ``sys.exit(1)``. Tests disable via
    ``ROVER_REQUIRED_ENV_SKIP=1``.
    """
    if os.environ.get("ROVER_REQUIRED_ENV_SKIP", "") == "1":
        return

    path = yaml_path or os.environ.get(
        "ROVER_REQUIRED_ENV_PATH", DEFAULT_YAML_PATH
    )
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
    except FileNotFoundError:
        _fatal(
            f"{path} not found; bind-mount missing. Check docker-compose.yml "
            "volumes entry for /app/config/required-env.yaml."
        )
        sys.exit(2)
    except yaml.YAMLError as exc:
        _fatal(f"{path} is not valid YAML: {exc}")
        sys.exit(2)

    services = (doc or {}).get("services") or {}
    entries = services.get(SERVICE_NAME)
    if entries is None:
        _fatal(
            f"service block {SERVICE_NAME!r} missing from {path}; YAML is "
            "malformed or out of date."
        )
        sys.exit(2)

    failures: list[str] = []
    for entry in entries:
        _validate_entry(entry, failures)

    if failures:
        for f in failures:
            _fatal(f)
        _fatal(
            f"{len(failures)} env var violation(s); refusing to boot. "
            "See config/required-env.yaml for the authoritative shape."
        )
        sys.exit(1)
