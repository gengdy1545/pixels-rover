/**
 * @vitest-environment node
 *
 * Unit tests for ``classifySseError`` — the SSE-open recovery policy
 * that drives {@link openSSEStreamWithRetry}.
 *
 * Pin:
 *   - User-abort short-circuits regardless of underlying error shape.
 *   - Pre-stream network failures produce ``retryPreStream`` up to
 *     ``MAX_PRE_STREAM_NETWORK_RETRIES`` times with 1s/2s/4s backoff,
 *     then ``giveUpPreStream``.
 *   - Pre-stream UPSTREAM ApiError produces exactly one retry, then
 *     ``giveUpPreStream``.
 *   - Other ApiError categories (USER_INPUT / AUTH / RATE_LIMIT /
 *     INTERNAL) produce ``businessError`` without any retry.
 *   - Mid-stream disconnects always produce ``disconnectMidStream``,
 *     never retry — even for a network error on attempt 1 (because
 *     we've already observed events, and the backend has no reattach).
 *   - Non-Error thrown values (string, undefined) don't crash the
 *     classifier.
 */

import { describe, it, expect } from 'vitest';
import { ApiError } from '../../../shared/api';
import type { ErrorCategory } from '../../../shared/types/common';
import {
  classifySseError,
  backoffDelayMs,
  MAX_PRE_STREAM_NETWORK_RETRIES,
  PRE_STREAM_BACKOFF_BASE_MS,
  UPSTREAM_RETRY_DELAY_MS,
} from './sseErrorPolicy';

function apiErrorOf(
  category: ErrorCategory,
  httpStatus: number,
  errorCode: 'ANALYSIS_INVALID_ARGUMENT' | 'ANALYSIS_DATABASE_UNAVAILABLE' = 'ANALYSIS_INVALID_ARGUMENT',
): ApiError {
  return new ApiError({
    httpStatus,
    message: 'stub',
    details: { errorCode, category },
  });
}

describe('backoffDelayMs()', () => {
  it('follows 1s/2s/4s exponential schedule', () => {
    expect(backoffDelayMs(1)).toBe(PRE_STREAM_BACKOFF_BASE_MS);
    expect(backoffDelayMs(2)).toBe(PRE_STREAM_BACKOFF_BASE_MS * 2);
    expect(backoffDelayMs(3)).toBe(PRE_STREAM_BACKOFF_BASE_MS * 4);
  });

  it('clamps attempt<1 to the base delay (defensive)', () => {
    expect(backoffDelayMs(0)).toBe(PRE_STREAM_BACKOFF_BASE_MS);
    expect(backoffDelayMs(-5)).toBe(PRE_STREAM_BACKOFF_BASE_MS);
  });
});

describe('classifySseError() — abort short-circuit', () => {
  it('returns cancelled when abortedByUser, regardless of error shape', () => {
    expect(
      classifySseError(new TypeError('network'), {
        streamStarted: false,
        priorPreStreamAttempts: 0,
        upstreamRetryUsed: false,
        abortedByUser: true,
      }),
    ).toEqual({ kind: 'cancelled' });

    expect(
      classifySseError(apiErrorOf('UPSTREAM', 503), {
        streamStarted: true,
        priorPreStreamAttempts: 5,
        upstreamRetryUsed: true,
        abortedByUser: true,
      }),
    ).toEqual({ kind: 'cancelled' });
  });
});

describe('classifySseError() — pre-stream network retries', () => {
  it('first TypeError → retryPreStream with 1s backoff, attempt 1/3', () => {
    const decision = classifySseError(new TypeError('Failed to fetch'), {
      streamStarted: false,
      priorPreStreamAttempts: 0,
      upstreamRetryUsed: false,
      abortedByUser: false,
    });
    expect(decision).toEqual({
      kind: 'retryPreStream',
      attempt: 1,
      maxAttempts: MAX_PRE_STREAM_NETWORK_RETRIES,
      delayMs: 1000,
      reason: 'network',
    });
  });

  it('second TypeError → retryPreStream with 2s backoff, attempt 2/3', () => {
    const decision = classifySseError(new TypeError('fetch'), {
      streamStarted: false,
      priorPreStreamAttempts: 1,
      upstreamRetryUsed: false,
      abortedByUser: false,
    });
    expect(decision.kind).toBe('retryPreStream');
    if (decision.kind === 'retryPreStream') {
      expect(decision.attempt).toBe(2);
      expect(decision.delayMs).toBe(2000);
    }
  });

  it('third TypeError → retryPreStream with 4s backoff, attempt 3/3', () => {
    const decision = classifySseError(new TypeError('fetch'), {
      streamStarted: false,
      priorPreStreamAttempts: 2,
      upstreamRetryUsed: false,
      abortedByUser: false,
    });
    expect(decision.kind).toBe('retryPreStream');
    if (decision.kind === 'retryPreStream') {
      expect(decision.attempt).toBe(3);
      expect(decision.delayMs).toBe(4000);
    }
  });

  it('fourth TypeError → giveUpPreStream (budget exhausted)', () => {
    const decision = classifySseError(new TypeError('fetch'), {
      streamStarted: false,
      priorPreStreamAttempts: MAX_PRE_STREAM_NETWORK_RETRIES,
      upstreamRetryUsed: false,
      abortedByUser: false,
    });
    expect(decision.kind).toBe('giveUpPreStream');
    if (decision.kind === 'giveUpPreStream') {
      expect(decision.message.toLowerCase()).toContain('could not reach');
    }
  });

  it('detects network-like Error via message regex (fetch wrapper variants)', () => {
    const decision = classifySseError(new Error('fetch failed'), {
      streamStarted: false,
      priorPreStreamAttempts: 0,
      upstreamRetryUsed: false,
      abortedByUser: false,
    });
    expect(decision.kind).toBe('retryPreStream');
  });
});

describe('classifySseError() — pre-stream UPSTREAM one-shot', () => {
  it('first UPSTREAM ApiError → retryPreStream with fixed 1.5s delay', () => {
    const decision = classifySseError(apiErrorOf('UPSTREAM', 503), {
      streamStarted: false,
      priorPreStreamAttempts: 0,
      upstreamRetryUsed: false,
      abortedByUser: false,
    });
    expect(decision.kind).toBe('retryPreStream');
    if (decision.kind === 'retryPreStream') {
      expect(decision.reason).toBe('upstream');
      expect(decision.delayMs).toBe(UPSTREAM_RETRY_DELAY_MS);
    }
  });

  it('second UPSTREAM ApiError (upstreamRetryUsed=true) → giveUpPreStream', () => {
    const decision = classifySseError(apiErrorOf('UPSTREAM', 503), {
      streamStarted: false,
      priorPreStreamAttempts: 1,
      upstreamRetryUsed: true,
      abortedByUser: false,
    });
    expect(decision.kind).toBe('giveUpPreStream');
  });
});

describe('classifySseError() — business errors are never retried', () => {
  it.each([
    ['USER_INPUT', 400],
    ['AUTH', 401],
    ['RATE_LIMIT', 429],
    ['INTERNAL', 500],
  ] as const)('category=%s → businessError', (category, status) => {
    const apiError = apiErrorOf(category, status);
    const decision = classifySseError(apiError, {
      streamStarted: false,
      priorPreStreamAttempts: 0,
      upstreamRetryUsed: false,
      abortedByUser: false,
    });
    expect(decision.kind).toBe('businessError');
    if (decision.kind === 'businessError') {
      expect(decision.apiError).toBe(apiError);
    }
  });
});

describe('classifySseError() — mid-stream never retries', () => {
  it('TypeError after streamStarted → disconnectMidStream (even on attempt 1)', () => {
    const decision = classifySseError(new TypeError('network'), {
      streamStarted: true,
      priorPreStreamAttempts: 0,
      upstreamRetryUsed: false,
      abortedByUser: false,
    });
    expect(decision.kind).toBe('disconnectMidStream');
    if (decision.kind === 'disconnectMidStream') {
      // Copy must hint at the "check history" recovery path since the
      // backend session may still be running.
      expect(decision.message.toLowerCase()).toContain('history');
    }
  });

  it('UPSTREAM ApiError after streamStarted → disconnectMidStream, NOT retryPreStream', () => {
    const decision = classifySseError(apiErrorOf('UPSTREAM', 503), {
      streamStarted: true,
      priorPreStreamAttempts: 0,
      upstreamRetryUsed: false,
      abortedByUser: false,
    });
    expect(decision.kind).toBe('disconnectMidStream');
  });
});

describe('classifySseError() — unknown errors', () => {
  it('non-Error thrown value → giveUpPreStream with fallback message', () => {
    const decision = classifySseError('weird', {
      streamStarted: false,
      priorPreStreamAttempts: 0,
      upstreamRetryUsed: false,
      abortedByUser: false,
    });
    expect(decision.kind).toBe('giveUpPreStream');
  });

  it('Error with no network signature → giveUpPreStream, NOT retried', () => {
    const decision = classifySseError(new Error('something weird'), {
      streamStarted: false,
      priorPreStreamAttempts: 0,
      upstreamRetryUsed: false,
      abortedByUser: false,
    });
    expect(decision.kind).toBe('giveUpPreStream');
    if (decision.kind === 'giveUpPreStream') {
      expect(decision.message).toBe('something weird');
    }
  });
});
