# Gateway Lua unit tests

Lightweight [busted](https://lunarmodules.github.io/busted/) specs for the
APISIX plugins under `gateway/custom/apisix/plugins/`.

## What's covered

These are **unit tests**, not integration tests. They lock in the contracts
that are most likely to silently regress during refactors:

- `gateway-auth`
  - `write_error` envelope shape (backend.md §6.0): HTTP status, `requestId`,
    `details.errorCode`, `details.category`; absence of `apiVersion` / top-level
    `errorCode`.
  - §6.3.1 gateway-side `(status, errorCode, category)` registry round-trip.
  - `apply_csrf` behaviour across safe methods, missing cookie, mismatched
    cookie/header, and matching cookie/header.
  - `is_safe_method` / `should_skip_csrf` — the contract that CSRF is keyed on
    HTTP method alone, never on cookie presence (gateway.md §5.2).
  - `clear_identity_headers` — strips every `X-Auth-*` prefix, not only the
    three known names (gateway.md §3.2 — future-proofing against header
    injection).
  - `ensure_request_id` — propagate inbound or mint a new one.
  - `should_retry` — transient vs permanent upstream error classification.

- `gateway-ready`
  - `empty_probes_body` — 503 envelope when no probes are registered.
  - `build_verdict` — 200/503 verdict + per-component UP/DOWN derivation,
    including the edge where `capture_multi` returns `nil` for a subrequest.

Full HTTP-level integration (real nginx, real cookies, real introspection
upstream) is covered by `scripts/smoke.sh`, not here.

## Running

```bash
./gateway/tests/run.sh
```

First invocation builds a throwaway Docker image based on the same
`apache/apisix:3.9.1-debian` the production gateway uses (~1-2 min). Later
invocations reuse the cached image.

Forward args to busted after `--`:

```bash
./gateway/tests/run.sh --filter "apply_csrf"
./gateway/tests/run.sh spec/gateway_ready_spec.lua
```

Force a rebuild by deleting the image:

```bash
docker image rm pixels-gateway-tests
```

## Extending

- Stubs live in `stubs/`. When a plugin starts using a new `ngx.*` /
  `resty.*` API, add it there — do **not** no-op silently, because silent
  stubs mask real regressions.
- New specs go in `spec/` and follow the `describe / it` pattern. Prefer
  asserting on the structured `ngx_stub.captured.body` (decoded JSON) rather
  than regex'ing the raw payload.
- If you need a new private hook in a plugin, extend `_M._private` at the
  bottom of that plugin file; it's deliberately marked "tests only".
