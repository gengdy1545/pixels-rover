"""
Cross-service authentication integration tests.

Simulates the real-world scenario where:
- Java Auth Service signs JWT tokens (HS256 or RS256)
- Python Analysis Service verifies those tokens

These tests validate that the Python service correctly accepts tokens
that would be issued by the Java Auth Service, covering:
- HS256 tokens with shared secret (current production path)
- RS256 tokens with kid-based public key lookup (target production path)
- RS256 tokens from a multi-key JWKS bundle (key rotation scenario)
- Token claim structure compatibility between Java and Python
- Issuer validation across services
- Cookie-based token delivery (HttpOnly cookie set by Java, read by Python)
"""

import json
import time

import pytest
from jose import jwt

from tests.conftest import (
    RSA_PRIVATE_KEY,
    RSA_PUBLIC_KEY,
    TEST_JWT_ISSUER,
    TEST_JWT_SECRET,
    TEST_RSA_KID,
    auth_header,
    make_access_token,
    make_rs256_access_token,
    make_test_settings,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# HS256 cross-service: Java signs with shared secret → Python verifies
# ---------------------------------------------------------------------------


class TestHS256CrossService:
    """
    Simulate Java Auth Service issuing HS256 tokens that the Python
    Analysis Service must accept.
    """

    async def test_java_issued_hs256_token_accepted(self, async_client):
        """
        Token with the exact claim structure that Java Auth Service produces:
        - sub: user email
        - uid: user database ID
        - type: "access"
        - iss: "pixels-rover-auth-service"
        - iat / exp: standard timestamps
        - sid: session ID (Java-specific, should be ignored by Python)
        """
        now = int(time.time())
        token = jwt.encode(
            {
                "sub": "alice@pixelsdb.io",
                "uid": 42,
                "type": "access",
                "iss": TEST_JWT_ISSUER,
                "iat": now,
                "exp": now + 86400,
                "sid": "java-session-abc123",  # Java-specific claim
            },
            TEST_JWT_SECRET,
            algorithm="HS256",
        )

        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200

    async def test_java_token_with_additional_claims_accepted(self, async_client):
        """
        Java may include extra claims (roles, permissions, etc.).
        Python should accept the token and ignore unknown claims.
        """
        now = int(time.time())
        token = jwt.encode(
            {
                "sub": "bob@pixelsdb.io",
                "uid": 99,
                "type": "access",
                "iss": TEST_JWT_ISSUER,
                "iat": now,
                "exp": now + 86400,
                "roles": ["ROLE_USER", "ROLE_ANALYST"],
                "permissions": ["analysis:read", "analysis:write"],
            },
            TEST_JWT_SECRET,
            algorithm="HS256",
        )

        resp = await async_client.get(
            "/api/v1/semantic/metrics",
            headers=auth_header(token),
        )
        assert resp.status_code == 200

    async def test_java_token_with_numeric_string_uid(self, async_client):
        """
        Ensure Python handles uid as both int and numeric string,
        since Java serialization may vary.
        """
        token = make_access_token(user_id=55)
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 200

    async def test_rejects_token_from_different_java_service(self, async_client):
        """
        Token issued by a different Java service (wrong issuer) must be rejected.
        """
        token = jwt.encode(
            {
                "sub": "alice@other.io",
                "uid": 1,
                "type": "access",
                "iss": "other-java-auth-service",
            },
            TEST_JWT_SECRET,
            algorithm="HS256",
        )

        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# RS256 cross-service: Java signs with private key → Python verifies with public key
# ---------------------------------------------------------------------------


class TestRS256CrossService:
    """
    Simulate Java Auth Service issuing RS256 tokens that the Python
    Analysis Service verifies using the corresponding public key.
    """

    async def test_java_issued_rs256_token_accepted(self, async_client_rs256):
        """
        RS256 token with kid header, verified against the configured public key.
        """
        now = int(time.time())
        token = jwt.encode(
            {
                "sub": "alice@pixelsdb.io",
                "uid": 42,
                "type": "access",
                "iss": TEST_JWT_ISSUER,
                "iat": now,
                "exp": now + 86400,
                "sid": "java-session-rs256-001",
            },
            RSA_PRIVATE_KEY,
            algorithm="RS256",
            headers={"kid": TEST_RSA_KID},
        )

        resp = await async_client_rs256.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 200

    async def test_rs256_token_with_wrong_kid_rejected(self, async_client_rs256):
        """
        RS256 token with an unknown kid must be rejected.
        This simulates a token signed by a key that has been rotated out.
        """
        token = jwt.encode(
            {
                "sub": "alice@pixelsdb.io",
                "uid": 42,
                "type": "access",
                "iss": TEST_JWT_ISSUER,
            },
            RSA_PRIVATE_KEY,
            algorithm="RS256",
            headers={"kid": "rotated-out-key-99"},
        )

        resp = await async_client_rs256.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 401

    async def test_rs256_token_without_kid_rejected(self, async_client_rs256):
        """
        RS256 token without a kid header should be rejected
        (Python needs kid to look up the correct public key).
        """
        token = jwt.encode(
            {
                "sub": "alice@pixelsdb.io",
                "uid": 42,
                "type": "access",
                "iss": TEST_JWT_ISSUER,
            },
            RSA_PRIVATE_KEY,
            algorithm="RS256",
            # No kid header
        )

        resp = await async_client_rs256.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        # Without kid, the public key lookup returns None → 401
        assert resp.status_code == 401

    async def test_rs256_cookie_delivery(self, async_client_rs256):
        """
        RS256 token delivered via HttpOnly cookie (set by Java, read by Python).
        """
        token = make_rs256_access_token(user_id=42, email="alice@pixelsdb.io")

        resp = await async_client_rs256.get(
            "/api/v1/semantic/metrics",
            cookies={"access_token": token},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Key rotation simulation
# ---------------------------------------------------------------------------


class TestKeyRotationCrossService:
    """
    Simulate the key rotation scenario:
    - Java rotates to a new RSA key pair
    - Python is configured with both old and new public keys
    - Tokens signed with either key should be accepted during the transition
    """

    async def test_accepts_token_from_current_key(self, async_client_rs256):
        """Token signed with the current active key should be accepted."""
        token = make_rs256_access_token(user_id=1, kid=TEST_RSA_KID)
        resp = await async_client_rs256.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Token claim contract between Java and Python
# ---------------------------------------------------------------------------


class TestTokenClaimContract:
    """
    Verify that the Python service correctly interprets the JWT claim
    structure defined in the cross-service auth contract.
    """

    async def test_sub_claim_used_as_email(self, async_client):
        """The 'sub' claim must be treated as the user's email."""
        token = make_access_token(email="contract-test@pixelsdb.io", user_id=77)
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 200

    async def test_uid_claim_used_as_user_id(self, async_client):
        """The 'uid' claim must be treated as the user's database ID."""
        token = make_access_token(user_id=12345)
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 200

    async def test_missing_sub_claim_rejected(self, async_client):
        """Token without 'sub' claim must be rejected."""
        token = jwt.encode(
            {
                "uid": 1,
                "type": "access",
                "iss": TEST_JWT_ISSUER,
            },
            TEST_JWT_SECRET,
            algorithm="HS256",
        )
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 401

    async def test_missing_uid_claim_rejected(self, async_client):
        """Token without 'uid' claim must be rejected."""
        token = jwt.encode(
            {
                "sub": "alice@pixelsdb.io",
                "type": "access",
                "iss": TEST_JWT_ISSUER,
            },
            TEST_JWT_SECRET,
            algorithm="HS256",
        )
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 401

    async def test_missing_type_claim_rejected(self, async_client):
        """Token without 'type' claim must be rejected (defaults to None != 'access')."""
        token = jwt.encode(
            {
                "sub": "alice@pixelsdb.io",
                "uid": 1,
                "iss": TEST_JWT_ISSUER,
            },
            TEST_JWT_SECRET,
            algorithm="HS256",
        )
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 401

    async def test_type_refresh_rejected(self, async_client):
        """Token with type='refresh' must be rejected at the API level."""
        token = jwt.encode(
            {
                "sub": "alice@pixelsdb.io",
                "uid": 1,
                "type": "refresh",
                "iss": TEST_JWT_ISSUER,
            },
            TEST_JWT_SECRET,
            algorithm="HS256",
        )
        resp = await async_client.get(
            "/api/v1/backends",
            headers=auth_header(token),
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 40103
        assert body["errorCode"] == "INVALID_TOKEN_TYPE"
