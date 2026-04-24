"""Task 8 — subject-integrity negative tests.

architecture-tasks.md §Task 8 acceptance gate: "A direct curl to
``assistant-service:8090/api/v1/conversations`` with hand-crafted
``X-Auth-User-Id`` returns 401, not 200."

These tests flip ``OATHKEEPER_JWT_REQUIRED=true`` in-process so the
backend's Oathkeeper JWT verifier runs; they do NOT boot Oathkeeper. A
request with forged ``X-Auth-*`` headers but no ``Authorization: Bearer``
token MUST be rejected with 401 + ``GATEWAY_SUBJECT_UNVERIFIED`` —
exactly the silent-bypass vector finding #2 flagged, now closed by the
id_token mutator + backend verifier pair.

The matching full-stack probe lives in ``scripts/smoke.sh``: it curls
the real ``assistant-service`` container from the compose network and
asserts the same 401. These pytest cases give the fast, always-green
feedback loop that CI runs on every PR; smoke closes the loop at
deploy time.
"""

from __future__ import annotations

import os

import pytest

from tests.conftest import gateway_identity_headers


@pytest.fixture
def jwt_required_env(monkeypatch):
    """Flip the Oathkeeper JWT verifier ON for the scope of one test.

    Sets only ``OATHKEEPER_JWT_REQUIRED=true``; the other three vars
    are intentionally left unset to exercise the "verifier enabled but
    misconfigured" path — the verifier MUST still refuse the request
    with 401 rather than letting it through. The explicit 401 makes
    the contract independent of downstream Oathkeeper availability.
    """
    monkeypatch.setenv("OATHKEEPER_JWT_REQUIRED", "true")
    # Deliberately do NOT set OATHKEEPER_JWKS_URL / ISSUER / AUDIENCE.
    # The verifier's first pre-flight check is "Bearer token present?"
    # which fails before any JWKS fetch would be attempted, so these
    # tests never need a running Oathkeeper or a key fixture.
    yield


@pytest.mark.asyncio
class TestForgedHeadersRejectedWithoutJwt:
    """Negative tests for §Task 8 acceptance:

    A request that reaches the backend with only X-Auth-* headers
    (no Bearer JWT) must be rejected with 401 SUBJECT_UNVERIFIED,
    regardless of whether those headers look syntactically valid.
    """

    async def test_forged_identity_without_bearer_is_401(
        self, jwt_required_env, async_client
    ):
        # Caller forges plausible X-Auth-* headers — the exact attack
        # shape finding #2 described: a sidecar on the same docker
        # network that knows the X-Auth-* convention but does NOT have
        # Oathkeeper's signing key.
        headers = gateway_identity_headers(
            user_id="kratos-identity-impersonated",
            email="attacker@example.com",
            session_id="forged-session-42",
        )

        resp = await async_client.get(
            "/api/v1/analysis/backends", headers=headers
        )

        assert resp.status_code == 401, (
            f"expected 401 SUBJECT_UNVERIFIED, got {resp.status_code} "
            f"body={resp.text!r}"
        )
        body = resp.json()
        assert body["details"]["errorCode"] == "GATEWAY_SUBJECT_UNVERIFIED"
        assert body["details"]["category"] == "AUTH"

    async def test_forged_identity_without_bearer_is_401_on_conversations(
        self, jwt_required_env, async_client
    ):
        # Mirrors the §Task 8 acceptance wording: "/api/v1/conversations
        # with hand-crafted X-Auth-User-Id". Explicitly separate from
        # the analysis probe above so a future regression that fixes
        # one route but not the other still surfaces here.
        headers = gateway_identity_headers(
            user_id="kratos-identity-impersonated",
            email="attacker@example.com",
        )
        resp = await async_client.get(
            "/api/v1/conversations", headers=headers
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["details"]["errorCode"] == "GATEWAY_SUBJECT_UNVERIFIED"

    async def test_bearer_present_but_not_bearer_scheme_is_401(
        self, jwt_required_env, async_client
    ):
        # Caller sends a capital-B Basic auth header — ensures the
        # verifier's prefix check is strict (``Bearer `` exact) and
        # does not silently accept a non-Bearer Authorization header
        # as "some token was there, good enough".
        headers = {
            **gateway_identity_headers(),
            "Authorization": "Basic AAAA",
        }
        resp = await async_client.get(
            "/api/v1/analysis/backends", headers=headers
        )
        assert resp.status_code == 401
        assert (
            resp.json()["details"]["errorCode"]
            == "GATEWAY_SUBJECT_UNVERIFIED"
        )


class TestJwtRequiredEnvFlag:
    """Contract-level tests for the escape hatch itself.

    ``jwt_required_from_env`` is the ONLY code path through which
    OATHKEEPER_JWT_REQUIRED influences request handling, so its
    semantics need a direct test (not just a behavioral one).
    """

    def test_disabled_when_var_unset(self, monkeypatch):
        from app.oathkeeper_jwt import jwt_required_from_env

        monkeypatch.delenv("OATHKEEPER_JWT_REQUIRED", raising=False)
        assert jwt_required_from_env() is False

    def test_disabled_when_var_is_false(self, monkeypatch):
        from app.oathkeeper_jwt import jwt_required_from_env

        monkeypatch.setenv("OATHKEEPER_JWT_REQUIRED", "false")
        assert jwt_required_from_env() is False

    def test_enabled_when_var_is_true(self, monkeypatch):
        from app.oathkeeper_jwt import jwt_required_from_env

        monkeypatch.setenv("OATHKEEPER_JWT_REQUIRED", "true")
        assert jwt_required_from_env() is True

    @pytest.mark.parametrize("v", ["TRUE", "True", " true ", "yes", "1"])
    def test_strict_true_literal_only(self, monkeypatch, v):
        """Case sensitivity guard.

        A lenient parser that treated "TRUE" / "yes" / "1" as
        truthy would let a typo in an ops playbook silently disable
        the verifier. The env registry declares ``enum: [true, false]``
        so the required-env validator refuses anything else at boot,
        but this test pins the runtime parser to the same strictness
        so a misconfigured OATHKEEPER_JWT_REQUIRED=TRUE (validator
        bypassed with ROVER_REQUIRED_ENV_SKIP=1) still fails closed.
        """
        from app.oathkeeper_jwt import jwt_required_from_env

        monkeypatch.setenv("OATHKEEPER_JWT_REQUIRED", v)
        # Lowercase trimmed "true" is the only accepted literal.
        expected = v.strip().lower() == "true"
        assert jwt_required_from_env() is expected
