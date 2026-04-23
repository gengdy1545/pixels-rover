/**
 * Infrastructure-prefix error codes (`GATEWAY_*` / `INTERNAL_*`).
 *
 * **Source of truth**: [`gateway/error-codes.json`](../../../../gateway/error-codes.json).
 * `docs/development/backend.md §6.3.1` is a rendered view of that JSON and
 * this union is a hand-mirrored copy of the same set. Any addition /
 * removal MUST go to the JSON first, then:
 *   1. Run `scripts/generate-error-code-registry.py` to refresh §6.3.1.
 *   2. Mirror the new code here.
 *   3. Add the literal to the emitting plugin's `KNOWN_ERROR_CODES` table
 *      (gateway/custom/apisix/plugins/gateway-*.lua).
 *
 * `scripts/check-contracts.py` enforces the three-way invariant
 * (Lua source ⊆ plugin KNOWN set ⊆ JSON registry = this union, exact). Any
 * skew fails CI — never add an infra-prefix code that isn't in the JSON.
 *
 * See `common.ts` for how this type merges into the top-level `ErrorCode`
 * union (backend.md §6.3.2).
 */
export type InfraErrorCode =
  | 'GATEWAY_IDENTITY_MISSING'
  | 'GATEWAY_AUTH_REQUIRED'
  | 'GATEWAY_CSRF_INVALID'
  | 'GATEWAY_INTROSPECT_UNAVAILABLE'
  | 'GATEWAY_NOT_READY'
  | 'INTERNAL_AUTH_FAILED';
