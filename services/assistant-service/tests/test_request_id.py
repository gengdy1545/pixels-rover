"""Unit tests for ``app.request_id``.

These pin the three-rule fallback shape from ``backend.md §5``:

1. A ``missing-<8 hex>`` literal is produced (no UUID4 regression).
2. ``resolve_request_id`` distinguishes inbound vs fallback so callers can
   emit *exactly one* ``request_id_missing=true`` log per request.
3. The ``ensure_request_id`` shim stays backward-compatible for callers that
   do not care about the fallback signal (tests / task code already inside a
   context).
"""

from __future__ import annotations

import re

import pytest

from app.request_id import (
    FALLBACK_PREFIX,
    ensure_request_id,
    generate_fallback_request_id,
    resolve_request_id,
)


FALLBACK_RE = re.compile(r"^missing-[0-9a-f]{8}$")


class TestFallbackShape:
    """``missing-<8 hex>`` literal — never UUID4."""

    def test_generate_has_prefix_and_8_hex(self) -> None:
        value = generate_fallback_request_id()
        assert value.startswith(FALLBACK_PREFIX)
        assert FALLBACK_RE.match(value), value

    def test_generate_varies_between_calls(self) -> None:
        samples = {generate_fallback_request_id() for _ in range(32)}
        # 32 bits of randomness → collision probability vanishingly small.
        assert len(samples) == 32

    def test_no_uuid4_regression(self) -> None:
        # UUID4 is 36 chars with dashes — the old bug. The new fallback is
        # 8 hex chars + a 'missing-' prefix = 17 chars total.
        value = generate_fallback_request_id()
        assert len(value) == len(FALLBACK_PREFIX) + 8
        assert "-" not in value[len(FALLBACK_PREFIX):]


class TestResolveRequestId:
    """``resolve_request_id`` returns (id, is_fallback) honestly."""

    def test_present_inbound_passes_through_untouched(self) -> None:
        request_id, is_fallback = resolve_request_id("abc-123")
        assert request_id == "abc-123"
        assert is_fallback is False

    def test_empty_inbound_triggers_fallback(self) -> None:
        request_id, is_fallback = resolve_request_id("")
        assert is_fallback is True
        assert FALLBACK_RE.match(request_id), request_id

    def test_none_inbound_triggers_fallback(self) -> None:
        request_id, is_fallback = resolve_request_id(None)
        assert is_fallback is True
        assert FALLBACK_RE.match(request_id), request_id


class TestEnsureRequestIdShim:
    """Backward-compatible helper still returns a plain str for test code."""

    def test_returns_inbound_when_present(self) -> None:
        assert ensure_request_id("xyz-789") == "xyz-789"

    def test_returns_fallback_when_missing(self) -> None:
        value = ensure_request_id(None)
        assert FALLBACK_RE.match(value), value


@pytest.mark.asyncio
async def test_middleware_emits_single_warning_on_fallback(
    async_client, caplog,
) -> None:
    """Integration: a request without X-Request-Id logs exactly one
    ``request_id_missing=true`` warning per request, per backend.md §5 rule 1.
    """
    import logging

    caplog.set_level(logging.WARNING, logger="app.main")

    resp = await async_client.get("/health")
    assert resp.status_code == 200

    warnings = [
        rec for rec in caplog.records
        if "request_id_missing=true" in rec.getMessage()
    ]
    assert len(warnings) == 1, [rec.getMessage() for rec in caplog.records]
    msg = warnings[0].getMessage()
    assert "route=/health" in msg
    assert "method=GET" in msg
    assert "fallback=missing-" in msg


@pytest.mark.asyncio
async def test_middleware_no_warning_when_header_present(
    async_client, caplog,
) -> None:
    """When the gateway has already injected X-Request-Id, no warning fires."""
    import logging

    caplog.set_level(logging.WARNING, logger="app.main")

    resp = await async_client.get("/health", headers={"X-Request-Id": "gw-abc"})
    assert resp.status_code == 200

    warnings = [
        rec for rec in caplog.records
        if "request_id_missing=true" in rec.getMessage()
    ]
    assert warnings == []


# architecture-tasks §Task 15 acceptance:
# "Deliberately stripping X-Request-Id in a test raises the counter and
# fires the alert rule in a dry-run." The alert-rule dry-run is covered
# by the `request-id-missing-alert-rule-bound` contract below (static
# expression + label match against the Prometheus rule file); this
# asserts the runtime counter half — the observable signal the alert
# expression ultimately sums over.
#
# Implementation note: we deliberately DO NOT `from app.main import
# REQUEST_ID_MISSING_TOTAL` inside the test. The async_client fixture
# already imported `app.main` during FastAPI app construction, so the
# Counter singleton lives in prometheus_client.REGISTRY. Re-importing
# would be harmless IF main.py were a pure reference module — but
# main.py's top level also runs `validate_or_die()` via create_app(),
# which trips when the test process doesn't have /app/config bind-
# mounted. Reading via the public REGISTRY API keeps the test
# self-contained and exercises the exact code path Prometheus will
# scrape in production.
_MISSING_COUNTER_NAME = "assistant_request_id_missing_total"


def _counter_sample_for_route(route: str) -> float:
    from prometheus_client import REGISTRY

    for metric in REGISTRY.collect():
        if metric.name != "assistant_request_id_missing":
            continue
        for sample in metric.samples:
            if (
                sample.name == _MISSING_COUNTER_NAME
                and sample.labels.get("route") == route
            ):
                return sample.value
    return 0.0


@pytest.mark.asyncio
async def test_counter_increments_when_request_id_header_missing(
    async_client,
) -> None:
    before = _counter_sample_for_route("/health")

    # Deliberately omit X-Request-Id to trigger the fallback path.
    resp = await async_client.get("/health")
    assert resp.status_code == 200

    after = _counter_sample_for_route("/health")
    assert after == pytest.approx(before + 1.0), (
        f"{_MISSING_COUNTER_NAME}{{route='/health'}} did not increment: "
        f"before={before!r} after={after!r}. This is the signal Task 15's "
        f"AssistantRequestIdMissing alert rule sums over."
    )


@pytest.mark.asyncio
async def test_counter_unchanged_when_request_id_header_present(
    async_client,
) -> None:
    """Negative counterpart: gateway-wired path must NOT bump the counter.

    A counter that increments on every request (instead of only on the
    fallback path) would make Task 15's alert expression perpetually
    fire regardless of gateway health — a false-positive pattern that
    is almost as bad as a silent-failure pattern.
    """
    before = _counter_sample_for_route("/health")
    resp = await async_client.get(
        "/health", headers={"X-Request-Id": "gw-present-42"}
    )
    assert resp.status_code == 200
    after = _counter_sample_for_route("/health")
    assert after == pytest.approx(before), (
        f"counter must NOT increment when X-Request-Id is present: "
        f"before={before!r} after={after!r}"
    )
