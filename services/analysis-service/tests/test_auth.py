import unittest

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import get_current_user
from app.config import Settings
from app.error_codes import (
    AUTHENTICATION_REQUIRED,
    AUTHENTICATION_REQUIRED_NAME,
    INVALID_TOKEN,
    INVALID_TOKEN_NAME,
    INVALID_TOKEN_TYPE,
    INVALID_TOKEN_TYPE_NAME,
)

RSA_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDv4T16LB1TXAbE
CyjWC8x5axYM2hlr53lUk2f+lkT8NzFeW+lFh3D5M20hXpL29nnB6MGiBfLpXOpq
b4EmMaCLrXL7uQwgkxrtKRf2oS7ij4RXUskgDSKM+Zv6VNdXGPzK3XSJozS3/XSJ
O0Lc0fGmrumRWlbCMJ8cikDQaSum8ikfnb23/AWPauLI9bITzpDUIW3Xrr80SFeO
yNUwB6B6q8cgYWztfB8PZ+Kb7G6sFLa2l7q1pOdSvcCpypodi57AUGtv+m5h3J1e
fn8Ytv+VjuEdzDCVN9iKQrZt9pVAcl1MhAzC6tLb6ea6+VPCOzBU6Bt3BztaITyw
54DuV7bHAgMBAAECggEAdgAAXG1//YYbA+wTafvC2YWOgsL012o1+p9KfGeSRtml
rOucnCnMrqGYEN6zf83uRi+HtPqlLBubasEwMEggWCV6Fw7HwuxqRfi9g4J1jFiZ
+tTMADrF4MBW9LUwevVdQTPgBGbm441H+svOj86sx1hqqChe3kbJtmHiEUNzCDtK
npIpGXdu0ZuQnOMZhwcXJ7QjgBKbD0+B05GFKwAomw9AMkrIS4oXG68WXdXGcypb
PNcOADWW2CpV51xzl8oMvbnLh/vAbQE/BQVqVQfViGqdrRlC8P3QL4CYYsySDNoL
rbjfdf9d023SeqGUou7tY7c+JN9TSXexB/+d+W6coQKBgQD7ynRrCwAGRVwfAY/D
Q8J/7A+fLu/tDQqNEJo2eIMptZBsHTd3BSFGVc3OskZ2pfovneSS3ZkwWUZvswpp
OAlso0r0r7zIlDi7gilDD4XKZmuJDZ/frtnMg5mFbaQ21DLbPAAHijTEA0wGLy/s
PaXlomkK44IShT0aYTCPfkNaYQKBgQDz48/eSUJl8qVmeYVZ9ACQ+D4fkwvYhL1v
Po+/ByMtGvC2F9qXZ8g00ga5P8DgxQa1TXLG2EJrKVb/INOJAobzumZsVJO0/PE2
tcvzbO53+e/4W9d1y3xV9+iaiyGsSH1lAssnHChIuG90sr5woDuKyFAMXNwbL9x+
tpMmbS4yJwKBgQCRHmJyv2hINPmfNTsyg386U0e9q0PFEFsgao03D8Yo5+hRJ5Ws
F1zSOOnhU4ahI5BKmWn/65A6+XlLL5m0gwOLhaHR3OelgygfiilV6UBnIxifaSbX
uOL2qHJ3IHYg07Rr/uzVa6Z1wqCyf8fTFMTk0PJRwEZbfkd1SMbALTmMgQKBgEOu
ZcIvHGEETEg60vnaj8mrSjoi6XelpphXiTae+XEL997gkcXQhCu8WSdRfOojYzAv
FPn/i7cHWuAkMO/lpqO+h6vqcK8aPqpLGxUrlqXu01xdyFYlKRUGXiN9FtQjrcC5
XL02wCsmG7AL5nOE0+E4o5Y6ss5Mouj7K6zPQbGjAoGAZORm55LNypfuNA7llStp
aEb8uy06/e+Ey9AZvQqRu8NYfFoCwhQtXl5qNg6j7YuovxCtQCxiqe9zWdokYz+M
cffB8SkxFazha72dVKUcwPRNrS/UlYv1Txf684hilFIOncTYLWszTG7F3aB91O2a
/Lf0g2G//g1bw6VlhNAzsyw=
-----END PRIVATE KEY-----"""

RSA_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA7+E9eiwdU1wGxAso1gvM
eWsWDNoZa+d5VJNn/pZE/DcxXlvpRYdw+TNtIV6S9vZ5wejBogXy6Vzqam+BJjGg
i61y+7kMIJMa7SkX9qEu4o+EV1LJIA0ijPmb+lTXVxj8yt10iaM0t/10iTtC3NHx
pq7pkVpWwjCfHIpA0GkrpvIpH529t/wFj2riyPWyE86Q1CFt166/NEhXjsjVMAeg
eqvHIGFs7XwfD2fim+xurBS2tpe6taTnUr3AqcqaHYuewFBrb/puYdydXn5/GLb/
lY7hHcwwlTfYikK2bfaVQHJdTIQMwurS2+nmuvlTwjswVOgbdwc7WiE8sOeA7le2
xwIDAQAB
-----END PUBLIC KEY-----"""


def make_token(secret: str, payload: dict, algorithm: str = "HS256", headers: dict | None = None) -> str:
    from jose import jwt

    return jwt.encode(payload, secret, algorithm=algorithm, headers=headers)


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(jwt_secret="test-secret", jwt_issuer="test-issuer")

    def test_requires_bearer_token(self):
        with self.assertRaises(HTTPException) as context:
            get_current_user(None, self.settings)

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail["code"], AUTHENTICATION_REQUIRED)
        self.assertEqual(context.exception.detail["errorCode"], AUTHENTICATION_REQUIRED_NAME)

    def test_accepts_valid_access_token(self):
        token = make_token(
            self.settings.jwt_secret,
            {
                "sub": "alice@example.com",
                "uid": 7,
                "type": "access",
                "iss": self.settings.jwt_issuer,
            },
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        current_user = get_current_user(credentials, self.settings)

        self.assertEqual(current_user.user_id, 7)
        self.assertEqual(current_user.email, "alice@example.com")
        self.assertEqual(current_user.token_type, "access")

    def test_rejects_refresh_token(self):
        token = make_token(
            self.settings.jwt_secret,
            {
                "sub": "alice@example.com",
                "uid": 7,
                "type": "refresh",
                "iss": self.settings.jwt_issuer,
            },
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with self.assertRaises(HTTPException) as context:
            get_current_user(credentials, self.settings)

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail["code"], INVALID_TOKEN_TYPE)
        self.assertEqual(context.exception.detail["errorCode"], INVALID_TOKEN_TYPE_NAME)

    def test_rejects_token_with_unexpected_issuer(self):
        token = make_token(
            self.settings.jwt_secret,
            {
                "sub": "alice@example.com",
                "uid": 7,
                "type": "access",
                "iss": "unexpected-issuer",
            },
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with self.assertRaises(HTTPException) as context:
            get_current_user(credentials, self.settings)

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail["code"], INVALID_TOKEN)
        self.assertEqual(context.exception.detail["errorCode"], INVALID_TOKEN_NAME)

    def test_rejects_token_with_missing_user_id(self):
        token = make_token(
            self.settings.jwt_secret,
            {
                "sub": "alice@example.com",
                "type": "access",
                "iss": self.settings.jwt_issuer,
            },
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with self.assertRaises(HTTPException) as context:
            get_current_user(credentials, self.settings)

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail["code"], INVALID_TOKEN)
        self.assertEqual(context.exception.detail["errorCode"], INVALID_TOKEN_NAME)

    def test_accepts_valid_rs256_access_token(self):
        rsa_settings = Settings(
            jwt_secret="test-secret",
            jwt_issuer="test-issuer",
            jwt_algorithm="RS256",
            jwt_active_kid="rsa-key-1",
            jwt_public_key_pem=RSA_PUBLIC_KEY,
        )
        token = make_token(
            RSA_PRIVATE_KEY,
            {
                "sub": "alice@example.com",
                "uid": 12,
                "type": "access",
                "iss": rsa_settings.jwt_issuer,
            },
            algorithm="RS256",
            headers={"kid": "rsa-key-1"},
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        current_user = get_current_user(credentials, rsa_settings)

        self.assertEqual(current_user.user_id, 12)
        self.assertEqual(current_user.email, "alice@example.com")
        self.assertEqual(current_user.token_type, "access")

    def test_rejects_rs256_token_with_unknown_kid(self):
        rsa_settings = Settings(
            jwt_secret="test-secret",
            jwt_issuer="test-issuer",
            jwt_algorithm="RS256",
            jwt_active_kid="rsa-key-1",
        )
        token = make_token(
            RSA_PRIVATE_KEY,
            {
                "sub": "alice@example.com",
                "uid": 12,
                "type": "access",
                "iss": rsa_settings.jwt_issuer,
            },
            algorithm="RS256",
            headers={"kid": "missing-key"},
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        with self.assertRaises(HTTPException) as context:
            get_current_user(credentials, rsa_settings)

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail["code"], INVALID_TOKEN)
        self.assertEqual(context.exception.detail["errorCode"], INVALID_TOKEN_NAME)

    def test_accepts_rs256_token_from_public_keys_json(self):
        rsa_settings = Settings(
            jwt_secret="test-secret",
            jwt_issuer="test-issuer",
            jwt_algorithm="RS256",
            jwt_active_kid="rsa-key-1",
            jwt_public_keys_json='{"rsa-key-1":"'
            + RSA_PUBLIC_KEY.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
            + '"}',
        )
        token = make_token(
            RSA_PRIVATE_KEY,
            {
                "sub": "alice@example.com",
                "uid": 99,
                "type": "access",
                "iss": rsa_settings.jwt_issuer,
            },
            algorithm="RS256",
            headers={"kid": "rsa-key-1"},
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        current_user = get_current_user(credentials, rsa_settings)

        self.assertEqual(current_user.user_id, 99)
        self.assertEqual(current_user.email, "alice@example.com")


if __name__ == "__main__":
    unittest.main()
