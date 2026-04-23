/**
 * @vitest-environment node
 *
 * Unit tests for ``ensureRequestId`` — the X-Request-Id lifecycle primitive
 * (frontend.md §4.6 hard rule).
 *
 * The contract under test:
 *
 *   1. ``ensureRequestId()`` with no argument mints a **fresh** id each call.
 *      Two independent logical requests must not collide on the same id
 *      (this is why we rejected a process-wide cache in favor of passing
 *      the existing id explicitly).
 *   2. ``ensureRequestId(existing)`` with a non-empty string returns the
 *      argument **verbatim** — this is what axios retries and SSE
 *      reconnects rely on to preserve log correlation.
 *   3. ``ensureRequestId(null | undefined | '')`` mints a fresh id, so the
 *      call site can uniformly pass "whatever was on the previous header"
 *      without pre-checking.
 *
 * The suite explicitly pins ``@vitest-environment node`` — the module under
 * test is a pure function that only touches ``crypto.randomUUID`` (which
 * exists in node ≥ 19 and in the ``vitest`` worker runtime), so we avoid
 * dragging jsdom into this small suite. See ``query-keys.test.ts`` for the
 * same rationale.
 */

import { describe, it, expect } from 'vitest';
import { createRequestId, ensureRequestId } from './requestId';

describe('createRequestId()', () => {
  it('returns a non-empty string', () => {
    const id = createRequestId();
    expect(typeof id).toBe('string');
    expect(id.length).toBeGreaterThan(0);
  });

  it('returns distinct ids across independent calls', () => {
    // Sample size large enough to detect collisions if the fallback path
    // were accidentally used with a low-entropy seed.
    const ids = new Set(Array.from({ length: 1024 }, () => createRequestId()));
    expect(ids.size).toBe(1024);
  });
});

describe('ensureRequestId() — X-Request-Id reuse invariant', () => {
  it('returns the existing id verbatim when given a non-empty string', () => {
    const captured = 'abc-123-existing';
    expect(ensureRequestId(captured)).toBe(captured);
  });

  it('returns a fresh id when called with no argument', () => {
    const a = ensureRequestId();
    const b = ensureRequestId();
    expect(a).not.toBe(b);
  });

  it('returns a fresh id when called with null / undefined / empty string', () => {
    // Uniform "coerce to fresh id" behavior lets axios/SSE call sites pass
    // ``config.headers['X-Request-Id']`` (which may be ``undefined``) or
    // ``streamRequestId`` (which starts at ``null``) without a pre-check.
    expect(ensureRequestId(null)).toEqual(expect.any(String));
    expect(ensureRequestId(undefined)).toEqual(expect.any(String));
    expect(ensureRequestId('')).toEqual(expect.any(String));

    const afresh = ensureRequestId(null);
    const bfresh = ensureRequestId(null);
    expect(afresh).not.toBe(bfresh);
  });

  it('preserves id across a simulated retry loop (axios 401 → refresh → retry)', () => {
    // The axios interceptor semantics we model here:
    //   - First pass: header slot is undefined → mint a fresh id.
    //   - Second pass on the *same* config after 401 refresh: header slot
    //     already holds the id from the first pass → reuse verbatim.
    const slot: { 'X-Request-Id'?: string } = {};

    slot['X-Request-Id'] = ensureRequestId(slot['X-Request-Id']);
    const firstAttemptId = slot['X-Request-Id'];

    slot['X-Request-Id'] = ensureRequestId(slot['X-Request-Id']);
    const retryAttemptId = slot['X-Request-Id'];

    expect(firstAttemptId).toBe(retryAttemptId);
  });

  it('preserves id across a simulated SSE reconnect loop', () => {
    // The SSE client captures the id in a closure-scoped variable and feeds
    // it back into ``buildCommonHeaders(streamRequestId)`` on reconnect.
    let streamRequestId: string | null = null;

    const openAttempt = () => {
      const id = ensureRequestId(streamRequestId);
      streamRequestId = id;
      return id;
    };

    const first = openAttempt();
    const second = openAttempt();
    const third = openAttempt();

    expect(first).toBe(second);
    expect(second).toBe(third);
  });
});
