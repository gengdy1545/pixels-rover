# Observability Roadmap

Pixels Rover currently relies on container stdout logs, `X-Request-Id`, and
service health/readiness endpoints. A separate log/metrics/tracing pipeline is
not part of the current baseline.

## Current Baseline

- APISIX emits gateway logs and carries `X-Request-Id`.
- Frontend API clients send `X-Request-Id`.
- Assistant-service consumes the inbound request id for log correlation.
- Assistant-service exports
  `assistant_request_id_missing_total{route="..."}` from `/metrics` whenever
  it has to synthesize a fallback request id. This should remain zero in a
  correctly wired gateway path.
- `/gateway/live` is process liveness.
- `/gateway/ready` aggregates Kratos, Oathkeeper, Ory UI, and assistant-service.
- Gateway `/metrics` is explicitly denied; scrapers must target the
  assistant-service port from the observability network.

## Stage A Watch List

- Alert expression once Prometheus is wired:
  `sum(rate(assistant_request_id_missing_total[5m])) > 0` for 5 minutes.
  Treat this as gateway/header propagation misconfiguration, not as a user
  authentication problem.

## Deferred Pipeline

Prometheus, Loki, OpenTelemetry, Jaeger, and similar components are deferred
until the project has either multiple production instances, a compliance
requirement for centralized log retention, or repeated incidents where local
container logs are insufficient for diagnosis.

## Non-Negotiable Contracts

- Preserve `X-Request-Id` from browser to gateway to business service.
- Keep gateway and service health/readiness endpoints stable.
- Do not log secrets, cookies, Kratos session ids, or raw identity payloads.
- When a metrics pipeline is introduced, add the collector and dashboards in
  the same change as any new stable metric names.
