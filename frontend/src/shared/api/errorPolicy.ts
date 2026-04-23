/**
 * Consumer-side category-routing helpers for `ApiError`.
 *
 * backend.md §6.3.2 defines a two-tier dispatch contract for error UX:
 *
 *   1. Precise branch — `switch (err.details.errorCode)` for user-visible
 *      copy that depends on the exact root cause (e.g. "wrong captcha" vs
 *      "demo mode read-only").
 *   2. Coarse bucket — `switch (err.details.category)` for the generic
 *      "can I retry this?" / "should I bounce to login?" / "is this a
 *      permanent user-input problem?" shape.
 *
 * This module owns the **coarse-bucket** decisions. Features that need
 * UX branching import from here instead of re-reading `err.httpStatus`:
 * keeping the mapping in one file is what the "错误映射完全切到
 * `gateway/error-codes.json.category`" task in `.notes/todolist.md §11` is
 * asking for — the SSOT is the JSON's `category` + `retryable` columns,
 * and the consumer side must not re-derive those from HTTP status numbers.
 *
 * The module is **client-only policy** — it does not import axios, does
 * not touch the wire, and has no side effects. It reads `ApiError` (which
 * the network layer has already normalized from the response envelope)
 * and returns plain-data decisions a component can act on.
 */

import { ApiError } from './apiError';
import type { ErrorCategory, ErrorCode } from '../types/common';

// ---------------------------------------------------------------------------
// Retryable policy
// ---------------------------------------------------------------------------

/**
 * Infra-prefix codes (GATEWAY_* / INTERNAL_*) whose `retryable` flag in
 * `gateway/error-codes.json` is `true`. Hand-mirrored here so that feature
 * code can ask "should I offer a 'retry' button?" without reaching for the
 * JSON or HTTP status number. `scripts/check-contracts.py` asserts this set
 * matches the JSON's retryable-infra subset (see the
 * `frontend-retryable-infra-codes-match-json` check).
 *
 * Business-prefix codes (AUTH_* / ANALYSIS_* / ...) never appear here —
 * their retryability is category-driven (see `isRetryableCategory`). If a
 * specific business code needs a non-default retryability, add it as a
 * per-code exception below rather than widening this set; that keeps the
 * invariant "infra codes are JSON-driven, business codes are
 * category-driven" legible.
 */
const RETRYABLE_INFRA_ERROR_CODES: ReadonlySet<ErrorCode> = new Set<ErrorCode>([
  'GATEWAY_CSRF_INVALID',
  'GATEWAY_INTROSPECT_UNAVAILABLE',
  'GATEWAY_NOT_READY',
]);

/**
 * Which categories are retryable by default. Based on backend.md §6.3.2:
 *
 * - `UPSTREAM` — by definition a transient upstream dependency failure
 *   (database down, LLM API rate limit, introspect unreachable). Safe to
 *   offer a retry; the C3 degradation-mode contract (backend.md §6.7)
 *   specifically picks 503 + `UPSTREAM` so clients know to back off and
 *   try again rather than clear state and bounce to login.
 * - `RATE_LIMIT` — retryable after the server-specified `retryAfterSec`
 *   hint (when present on `details`).
 * - `AUTH` — NOT retryable at the coarse level; the axios client already
 *   handles the single legitimate auto-retry (access-token refresh). Any
 *   `AUTH` that surfaces to UI means "user intervention required" — e.g.
 *   captcha refresh or re-login — and a blind retry would just loop.
 * - `USER_INPUT` — not retryable; wait for the user to correct the form.
 * - `INTERNAL` — not retryable; the server hit an unhandled case and
 *   another attempt with the same payload is likely to reproduce.
 */
const RETRYABLE_CATEGORIES: ReadonlySet<ErrorCategory> = new Set<ErrorCategory>([
  'UPSTREAM',
  'RATE_LIMIT',
]);

/**
 * Returns true if the error looks safe to retry by user action
 * (e.g. pressing a "retry" button on an error toast). The decision walks
 * the two-tier dispatch:
 *
 *   1. If we recognize the exact `errorCode`, use that verdict (lets us
 *      override a category default for one specific code).
 *   2. Otherwise, key off `category`.
 *   3. If neither is present (framework-level fallback, §6.5), treat as
 *      non-retryable — the server has leaked an unhandled exception and we
 *      don't have enough information to claim idempotency.
 */
export function isRetryable(error: ApiError): boolean {
  const code = error.errorCode;
  if (code && RETRYABLE_INFRA_ERROR_CODES.has(code)) {
    return true;
  }
  const category = error.category;
  if (category && RETRYABLE_CATEGORIES.has(category)) {
    return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Category bucketing for UX dispatch
// ---------------------------------------------------------------------------

/**
 * Narrow UX buckets for the "what should the app DO about this error"
 * question. Features use this in error-handling code paths instead of
 * re-reading `httpStatus` — e.g. a router-level boundary:
 *
 *     switch (categorize(err)) {
 *       case 'auth-required': navigate('/login'); break;
 *       case 'upstream-unavailable': showRetryableToast(err); break;
 *       case 'user-input': highlightForm(err.details.field); break;
 *       ...
 *     }
 *
 * The enum is slightly finer-grained than the raw `ErrorCategory` so the
 * UX can distinguish "we don't know what happened" (`unknown`) from
 * "server told us INTERNAL" (`server-error`), and "auto-refresh already
 * failed" (`auth-required`) from generic AUTH codes that came from a
 * specific flow (captcha, demo-mode).
 */
export type ApiErrorBucket =
  | 'auth-required'
  | 'user-input'
  | 'rate-limited'
  | 'upstream-unavailable'
  | 'server-error'
  | 'unknown';

export function categorize(error: ApiError): ApiErrorBucket {
  const category = error.category;
  switch (category) {
    case 'AUTH':
      return 'auth-required';
    case 'USER_INPUT':
      return 'user-input';
    case 'RATE_LIMIT':
      return 'rate-limited';
    case 'UPSTREAM':
      return 'upstream-unavailable';
    case 'INTERNAL':
      return 'server-error';
    default:
      // `category` absent — framework-level uncaught-exception fallback
      // (backend.md §6.5). Surface as "unknown" so the shell can show a
      // generic "something went wrong" with the request id for log
      // correlation, rather than guessing based on HTTP status.
      return 'unknown';
  }
}

// ---------------------------------------------------------------------------
// Rate-limit hint extraction
// ---------------------------------------------------------------------------

/**
 * Pull the ``retryAfterSec`` hint off a rate-limit error's `details` bag
 * when present. Returns ``null`` when absent or malformed so callers can
 * fall back to their own default backoff rather than guessing.
 *
 * The hint is typed as ``[key: string]: unknown`` on the envelope — this
 * helper narrows it to ``number`` in one place so UI code doesn't spread
 * ad-hoc ``typeof`` checks across features.
 */
export function retryAfterSec(error: ApiError): number | null {
  const hint = error.details?.['retryAfterSec'];
  if (typeof hint === 'number' && Number.isFinite(hint) && hint >= 0) {
    return hint;
  }
  return null;
}
