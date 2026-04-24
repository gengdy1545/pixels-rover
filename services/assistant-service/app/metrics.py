"""Process-level Prometheus metrics for assistant-service.

architecture-tasks §Task 15 — subject-integrity log invariant.

This module is the SINGLE writer of module-level prometheus_client
Counter / Histogram / Gauge singletons used across the service. Keeping
them here (rather than inlining their construction in ``app.main``)
serves two independent goals:

1.  ``app.main`` has non-trivial import-time side effects: it calls
    ``create_app()`` at the bottom of the module, which in turn calls
    ``validate_or_die()`` against the required-env YAML. Test harnesses
    that need to peek at a counter singleton would otherwise have to
    either (a) import ``app.main`` — triggering that side effect and
    failing when the bind-mount is absent — or (b) build their own
    shadow counter, which silently breaks the "warning and counter
    bump happen at the same point" invariant. Owning the singletons
    here lets both production and tests share exactly one
    ``CollectorRegistry`` entry without pulling in the FastAPI app
    construction path.

2.  Adding further metrics in later tasks (Task 14's metrics port
    work, Task 17's worker seam) is a one-file edit rather than
    pollution of ``app.main``'s already-crowded module top.

The exact metric name / label set here is pinned by the
``request-id-missing-counter-wired`` contract in
``scripts/check-contracts.py``. Renaming the counter or relabeling it
without the contract's blessing silently breaks the
``AssistantRequestIdMissing`` Prometheus alert rule in
``config/observability/prometheus-rules.request-id-missing.yml``.
"""
from __future__ import annotations

from prometheus_client import Counter

# architecture-tasks §Task 15 — request_id_missing invariant.
#
# Incremented at exactly the same site that emits the
# ``request_id_missing=true`` warning log (``app.main.add_request_id``
# middleware). A non-zero rate means the gateway is bypassed or the
# APISIX global request-id plugin is misconfigured — it is NOT a user-
# facing auth/validation failure. See
# ``docs/runbooks/observability-roadmap.md`` §Stage A Watch List for
# the alert expression operators will page on.
REQUEST_ID_MISSING_TOTAL = Counter(
    "assistant_request_id_missing_total",
    "Requests that arrived at assistant-service without a gateway X-Request-Id.",
    ("route",),
)
