from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pcdog_runtime.web_auth import (
    AuthenticationError,
    LOGIN_MAX_FAILURES,
    SESSION_TTL,
    WebAuthenticator,
    WebAuthError,
    hash_password,
)


class WebAuthTests(unittest.TestCase):
    password = "correct horse battery staple"

    def test_scrypt_record_never_contains_password_and_round_trips(self) -> None:
        record = hash_password(self.password, salt=b"x" * 16)
        self.assertNotIn(self.password, json.dumps(record))
        authenticator = WebAuthenticator.from_password(self.password)
        session = authenticator.login(self.password, "127.0.0.1")
        self.assertGreater(session.expires_at, datetime.now(UTC))
        self.assertEqual(authenticator.session(session.token), session)
        authenticator.require_write(session.token, session.csrf_token)
        with self.assertRaises(AuthenticationError) as error:
            authenticator.require_write(session.token, "not-the-token")
        self.assertEqual(error.exception.code, "CSRF_INVALID")

    def test_missing_config_is_safe_and_does_not_allow_login(self) -> None:
        with TemporaryDirectory() as directory:
            authenticator = WebAuthenticator.from_config(Path(directory) / "missing.json")
        self.assertFalse(authenticator.configured)
        with self.assertRaises(AuthenticationError) as error:
            authenticator.login(self.password, "127.0.0.1")
        self.assertEqual(error.exception.code, "AUTH_NOT_CONFIGURED")

    def test_invalid_config_and_short_password_are_rejected(self) -> None:
        with self.assertRaises(WebAuthError):
            hash_password("za krótkie")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "web-auth.json"
            path.write_text('{"version":1,"password":"invalid"}', encoding="utf-8")
            with self.assertRaises(WebAuthError):
                WebAuthenticator.from_config(path)

    def test_failed_login_is_rate_limited_per_client(self) -> None:
        authenticator = WebAuthenticator.from_password(self.password)
        for _ in range(LOGIN_MAX_FAILURES):
            with self.assertRaises(AuthenticationError) as error:
                authenticator.login("wrong password", "127.0.0.1")
            self.assertEqual(error.exception.code, "INVALID_CREDENTIALS")
        with self.assertRaises(AuthenticationError) as error:
            authenticator.login(self.password, "127.0.0.1")
        self.assertEqual(error.exception.code, "LOGIN_RATE_LIMITED")
        self.assertTrue(authenticator.login(self.password, "127.0.0.2").token)

    def test_config_round_trip(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "web-auth.json"
            path.write_text(json.dumps({"version": 1, "password": hash_password(self.password)}), encoding="utf-8")
            authenticator = WebAuthenticator.from_config(path)
        self.assertTrue(authenticator.login(self.password, "127.0.0.1").token)


if __name__ == "__main__":
    unittest.main()
