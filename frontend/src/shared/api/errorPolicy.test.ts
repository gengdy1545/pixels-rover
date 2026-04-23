/**
 * @vitest-environment node
 *
 * Tests for the consumer-side error-policy helpers
 * (`isRetryable` / `categorize` / `retryAfterSec`).
 *
 * These helpers collectively implement the "category-routed error
 * handling" requirement pulled from ``.notes/todolist.md §11`` — the
 * SSOT for retryability/bucketing is ``gateway/error-codes.json``'s
 * `category` + `retryable` columns, and this suite pins the mapping so
 * that the JSON-to-UX bridge doesn't silently regress.
 *
 * ``node`` env because the helpers are pure TS (no DOM, no fetch).
 */

import { describe, it, expect } from 'vitest';
import { ApiError } from './apiError';
import { isRetryable, categorize, retryAfterSec } from './errorPolicy';
import type { ErrorCategory, ErrorCode } from '../types/common';

function makeError(opts: {
  httpStatus?: number;
  errorCode?: ErrorCode;
  category?: ErrorCategory;
  details?: Record<string, unknown>;
}): ApiError {
  const { httpStatus = 500, errorCode, category, details } = opts;
  const merged = errorCode && category
    ? { errorCode, category, ...(details ?? {}) }
    : details;
  return new ApiError({
    httpStatus,
    message: 'stub',
    details: merged as ApiError['details'],
  });
}

describe('isRetryable()', () => {
  it('is true for UPSTREAM category (C3 degradation-mode contract)', () => {
    const err = makeError({
      httpStatus: 503,
      errorCode: 'ANALYSIS_DATABASE_UNAVAILABLE',
      category: 'UPSTREAM',
    });
    expect(isRetryable(err)).toBe(true);
  });

  it('is true for RATE_LIMIT category', () => {
    const err = makeError({
      httpStatus: 429,
      errorCode: 'ANALYSIS_INVALID_ARGUMENT',
      category: 'RATE_LIMIT',
    });
    expect(isRetryable(err)).toBe(true);
  });

  it('is false for AUTH category (auto-retry already exhausted by client)', () => {
    const err = makeError({
      httpStatus: 401,
      errorCode: 'GATEWAY_AUTH_REQUIRED',
      category: 'AUTH',
    });
    expect(isRetryable(err)).toBe(false);
  });

  it('is false for USER_INPUT (wait for user correction)', () => {
    const err = makeError({
      httpStatus: 400,
      errorCode: 'AUTH_INVALID_ARGUMENT',
      category: 'USER_INPUT',
    });
    expect(isRetryable(err)).toBe(false);
  });

  it('is false for INTERNAL (framework unhandled)', () => {
    const err = makeError({
      httpStatus: 500,
      errorCode: 'GATEWAY_IDENTITY_MISSING',
      category: 'INTERNAL',
    });
    expect(isRetryable(err)).toBe(false);
  });

  it('honors the per-code GATEWAY_CSRF_INVALID override over AUTH category default', () => {
    // CSRF failures are AUTH-category but specifically retryable per
    // gateway/error-codes.json — fetch a fresh XSRF cookie and retry once.
    const err = makeError({
      httpStatus: 403,
      errorCode: 'GATEWAY_CSRF_INVALID',
      category: 'AUTH',
    });
    expect(isRetryable(err)).toBe(true);
  });

  it('is false when details are entirely absent (§6.5 fallback)', () => {
    const err = makeError({ httpStatus: 500 });
    expect(isRetryable(err)).toBe(false);
  });
});

describe('categorize()', () => {
  it.each<[ErrorCategory, ReturnType<typeof categorize>]>([
    ['AUTH', 'auth-required'],
    ['USER_INPUT', 'user-input'],
    ['RATE_LIMIT', 'rate-limited'],
    ['UPSTREAM', 'upstream-unavailable'],
    ['INTERNAL', 'server-error'],
  ])('maps %s → %s', (category, bucket) => {
    const err = makeError({
      errorCode: 'AUTH_INVALID_ARGUMENT',
      category,
    });
    expect(categorize(err)).toBe(bucket);
  });

  it('maps missing details (§6.5 fallback) → "unknown"', () => {
    expect(categorize(makeError({ httpStatus: 500 }))).toBe('unknown');
  });
});

describe('retryAfterSec()', () => {
  it('returns the numeric hint when details.retryAfterSec is a positive number', () => {
    const err = makeError({
      httpStatus: 429,
      errorCode: 'ANALYSIS_INVALID_ARGUMENT',
      category: 'RATE_LIMIT',
      details: { retryAfterSec: 30 },
    });
    expect(retryAfterSec(err)).toBe(30);
  });

  it('returns null when the hint is absent', () => {
    const err = makeError({
      httpStatus: 429,
      errorCode: 'ANALYSIS_INVALID_ARGUMENT',
      category: 'RATE_LIMIT',
    });
    expect(retryAfterSec(err)).toBeNull();
  });

  it('returns null when the hint is a non-number (type safety)', () => {
    const err = makeError({
      httpStatus: 429,
      errorCode: 'ANALYSIS_INVALID_ARGUMENT',
      category: 'RATE_LIMIT',
      details: { retryAfterSec: '30' },
    });
    expect(retryAfterSec(err)).toBeNull();
  });

  it('returns null when the hint is negative / NaN', () => {
    const errNeg = makeError({
      httpStatus: 429,
      errorCode: 'ANALYSIS_INVALID_ARGUMENT',
      category: 'RATE_LIMIT',
      details: { retryAfterSec: -5 },
    });
    const errNaN = makeError({
      httpStatus: 429,
      errorCode: 'ANALYSIS_INVALID_ARGUMENT',
      category: 'RATE_LIMIT',
      details: { retryAfterSec: Number.NaN },
    });
    expect(retryAfterSec(errNeg)).toBeNull();
    expect(retryAfterSec(errNaN)).toBeNull();
  });
});
