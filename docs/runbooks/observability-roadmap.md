# Observability Roadmap

Pixels Rover currently relies on container stdout logs, `X-Request-Id`, and
service health/readiness endpoints. A separate log/metrics/tracing pipeline is
not part of the current baseline.

## Current Baseline

- APISIX emits gateway logs and carries `X-Request-Id`.
- Frontend API clients send `X-Request-Id`.
- Assistant-service consumes the inbound request id for log correlation.
- `/gateway/live` is process liveness.
- `/gateway/ready` aggregates Kratos, Oathkeeper, Ory UI, and assistant-service.

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
