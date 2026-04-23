#!/usr/bin/env python3
"""Hard-validate required env vars at gateway boot.

Called from gateway/entrypoint.sh BEFORE APISIX loads the rendered
apisix.yaml, so any violation fails the container at start instead of
turning every first request into an opaque upstream 500.

Design contract (backend.md §13, todolist §14):

  * SSOT is config/required-env.yaml (bind-mounted at
    /usr/local/apisix/conf/required-env.yaml). Adding / removing /
    tightening a var here NEVER requires touching this script — all
    shape lives in the YAML.

  * Exit codes:

      0   all required gateway-profile vars present + valid.
      1   at least one violation. stderr carries one FATAL line per
          violation; entrypoint.sh's `set -eu` surfaces the non-zero
          exit as a boot failure (compose logs the container as
          restarted / exited).
      2   YAML or schema itself is malformed (fail loudly; the contract
          layer is broken and no amount of env fixup can proceed).

  * Enforcement semantics mirror exactly what
    scripts/check-contracts.py's DSL validator asserts on the static
    config — this script is the RUNTIME enforcement half of the same
    contract. Stay strict: do NOT coerce values, do NOT silently
    normalise case, do NOT accept surrounding whitespace.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    print(
        "FATAL gateway: PyYAML not available inside gateway image; "
        "Dockerfile install step regressed (see gateway/Dockerfile)",
        file=sys.stderr,
    )
    sys.exit(2)


SERVICE_NAME = "gateway"


def _fatal(msg: str) -> None:
    print(f"FATAL gateway/required-env: {msg}", file=sys.stderr)


def _value_for(name: str) -> str:
    """Return env value AS-IS. Empty / unset collapse to ''.

    Whitespace is NOT stripped: an operator who wrote ``FOO= `` has a
    broken .env file, and we want the validator to catch it — not
    silently forgive it.
    """
    return os.environ.get(name, "")


def _validate_entry(entry: dict, failures: list[str]) -> None:
    name = entry["name"]
    value = _value_for(name)

    required = entry.get("required", False)
    required_when = entry.get("required_when")
    forbidden_when = entry.get("forbidden_when")
    other_matches = None

    if required_when or forbidden_when:
        clause = required_when or forbidden_when
        # Schema guarantees "OTHER=value" shape, but be defensive.
        if "=" not in clause:
            failures.append(
                f"{name}: malformed required_when/forbidden_when clause "
                f"{clause!r}; expected OTHER=value"
            )
            return
        other_name, expected = clause.split("=", 1)
        other_value = _value_for(other_name)
        other_matches = other_value == expected

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
            failures.append(
                f"{name} is required ("
                + ("unconditional" if required else f"because {required_when}")
                + f") but is empty or unset. See config/required-env.yaml "
                f"for description."
            )
        return

    if "enum" in entry and value not in entry["enum"]:
        failures.append(
            f"{name} = {value!r} is not in allowed enum "
            f"{entry['enum']} (strict string match)."
        )

    for bad in entry.get("forbidden_values", []):
        if value == bad:
            failures.append(
                f"{name} = {value!r} matches forbidden placeholder "
                f"{bad!r}; refusing to boot."
            )

    if "min_utf8_bytes" in entry:
        if len(value.encode("utf-8")) < entry["min_utf8_bytes"]:
            failures.append(
                f"{name} is {len(value.encode('utf-8'))} UTF-8 bytes, "
                f"below minimum {entry['min_utf8_bytes']}."
            )

    if entry.get("file_must_exist"):
        p = Path(value)
        if not p.is_file():
            failures.append(
                f"{name} = {value!r} is not a regular file "
                f"(validator runs AFTER bind-mount; check your compose "
                f"volume and host-side provisioning)."
            )
        else:
            try:
                p.open("rb").close()
            except OSError as exc:
                failures.append(
                    f"{name} = {value!r} is not readable: {exc}"
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yaml",
        default="/usr/local/apisix/conf/required-env.yaml",
        help="path to required-env.yaml (bind-mounted at container start)",
    )
    parser.add_argument(
        "--service",
        default=SERVICE_NAME,
        help="service block to validate (default: gateway)",
    )
    args = parser.parse_args()

    try:
        with open(args.yaml, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
    except FileNotFoundError:
        _fatal(
            f"{args.yaml} not found; bind-mount missing or image built "
            "without config/required-env.yaml. Check docker-compose.yml."
        )
        return 2
    except yaml.YAMLError as exc:
        _fatal(f"{args.yaml} is not valid YAML: {exc}")
        return 2

    services = (doc or {}).get("services") or {}
    entries = services.get(args.service)
    if entries is None:
        _fatal(
            f"service block {args.service!r} missing from {args.yaml}; "
            "YAML is malformed or out of date."
        )
        return 2

    failures: list[str] = []
    for entry in entries:
        _validate_entry(entry, failures)

    if failures:
        for f in failures:
            _fatal(f)
        _fatal(
            f"{len(failures)} env var violation(s); refusing to boot. "
            "Populate the missing / invalid values in .env and retry."
        )
        return 1

    print(
        f"gateway/required-env: all {len(entries)} required vars OK",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
