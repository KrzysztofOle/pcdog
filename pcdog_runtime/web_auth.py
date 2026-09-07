"""Lokalne hasło administratora, sesje i ochrona żądań Web Panelu."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import json
from pathlib import Path
import secrets
from threading import Lock
from typing import Final


CONFIG_VERSION: Final = 1
PASSWORD_MINIMUM_LENGTH: Final = 12
SESSION_COOKIE_NAME: Final = "pcdog_session"
SESSION_TTL: Final = timedelta(minutes=30)
LOGIN_WINDOW: Final = timedelta(minutes=10)
LOGIN_MAX_FAILURES: Final = 5


class WebAuthError(ValueError):
    """Błąd konfiguracji lub wejścia bez ujawniania sekretów."""


class AuthenticationError(WebAuthError):
    """Błąd uwierzytelnienia albo sesji."""

    def __init__(self, code: str, message: str, *, status: int = 401) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True, slots=True)
class PasswordRecord:
    salt: bytes
    digest: bytes


@dataclass(frozen=True, slots=True)
class Session:
    token: str
    csrf_token: str
    expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str, *, salt: bytes | None = None) -> dict[str, object]:
    """Tworzy serializowalny rekord scrypt; hasło nie trafia do wyniku."""

    _validate_password(password)
    salt = secrets.token_bytes(16) if salt is None else salt
    if len(salt) < 16:
        raise WebAuthError("Sól hasła jest zbyt krótka")
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return {
        "algorithm": "scrypt",
        "n": 2**14,
        "r": 8,
        "p": 1,
        "salt_b64": base64.b64encode(salt).decode("ascii"),
        "digest_b64": base64.b64encode(digest).decode("ascii"),
    }


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < PASSWORD_MINIMUM_LENGTH:
        raise WebAuthError(f"Hasło musi mieć co najmniej {PASSWORD_MINIMUM_LENGTH} znaków")
    if len(password) > 1024:
        raise WebAuthError("Hasło jest zbyt długie")


def _parse_password_record(value: object) -> PasswordRecord:
    if not isinstance(value, dict):
        raise WebAuthError("Konfiguracja hasła jest nieprawidłowa")
    allowed = {"algorithm", "n", "r", "p", "salt_b64", "digest_b64"}
    if set(value) != allowed or value.get("algorithm") != "scrypt":
        raise WebAuthError("Konfiguracja hasła jest nieprawidłowa")
    if (value.get("n"), value.get("r"), value.get("p")) != (2**14, 8, 1):
        raise WebAuthError("Konfiguracja hasła używa nieobsługiwanych parametrów")
    try:
        salt = base64.b64decode(value["salt_b64"], validate=True)
        digest = base64.b64decode(value["digest_b64"], validate=True)
    except (KeyError, TypeError, ValueError) as error:
        raise WebAuthError("Konfiguracja hasła jest nieprawidłowa") from error
    if len(salt) < 16 or len(digest) != 64:
        raise WebAuthError("Konfiguracja hasła jest nieprawidłowa")
    return PasswordRecord(salt=salt, digest=digest)


class WebAuthenticator:
    """Pamięciowy magazyn sesji; restart runtime celowo wylogowuje użytkownika."""

    def __init__(self, password_record: PasswordRecord | None) -> None:
        self._password_record = password_record
        self._sessions: dict[str, Session] = {}
        self._failed_attempts: defaultdict[str, deque[datetime]] = defaultdict(deque)
        self._lock = Lock()

    @classmethod
    def from_password(cls, password: str) -> WebAuthenticator:
        record = _parse_password_record(hash_password(password))
        return cls(record)

    @classmethod
    def from_config(cls, path: Path) -> WebAuthenticator:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(None)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise WebAuthError("Nie można odczytać konfiguracji uwierzytelnienia") from error
        if not isinstance(payload, dict) or set(payload) != {"version", "password"}:
            raise WebAuthError("Konfiguracja uwierzytelnienia jest nieprawidłowa")
        if payload["version"] != CONFIG_VERSION:
            raise WebAuthError("Konfiguracja uwierzytelnienia ma nieobsługiwaną wersję")
        return cls(_parse_password_record(payload["password"]))

    @property
    def configured(self) -> bool:
        return self._password_record is not None

    def login(self, password: str, client_ip: str) -> Session:
        with self._lock:
            self._require_configured()
            now = _utc_now()
            attempts = self._attempts_for(client_ip, now)
            if len(attempts) >= LOGIN_MAX_FAILURES:
                raise AuthenticationError("LOGIN_RATE_LIMITED", "Zbyt wiele nieudanych prób", status=429)
            if not self._verify_password(password):
                attempts.append(now)
                raise AuthenticationError("INVALID_CREDENTIALS", "Nieprawidłowe hasło")
            self._failed_attempts.pop(client_ip, None)
            session = Session(
                token=secrets.token_urlsafe(32),
                csrf_token=secrets.token_urlsafe(32),
                expires_at=now + SESSION_TTL,
            )
            self._sessions[session.token] = session
            return session

    def session(self, token: str | None) -> Session:
        with self._lock:
            self._require_configured()
            session = self._sessions.get(token or "")
            if session is None or session.expires_at <= _utc_now():
                self._sessions.pop(token or "", None)
                raise AuthenticationError("AUTH_REQUIRED", "Wymagane jest logowanie")
            return session

    def require_write(self, token: str | None, csrf_token: str | None) -> Session:
        session = self.session(token)
        if not csrf_token or not hmac.compare_digest(session.csrf_token, csrf_token):
            raise AuthenticationError("CSRF_INVALID", "Nieprawidłowe potwierdzenie żądania", status=403)
        return session

    def logout(self, token: str | None) -> None:
        with self._lock:
            if token:
                self._sessions.pop(token, None)

    def _verify_password(self, password: str) -> bool:
        if not isinstance(password, str) or len(password) > 1024:
            return False
        assert self._password_record is not None
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=self._password_record.salt,
            n=2**14,
            r=8,
            p=1,
        )
        return hmac.compare_digest(candidate, self._password_record.digest)

    def _require_configured(self) -> None:
        if not self.configured:
            raise AuthenticationError("AUTH_NOT_CONFIGURED", "Logowanie nie zostało jeszcze skonfigurowane", status=503)

    def _attempts_for(self, client_ip: str, now: datetime) -> deque[datetime]:
        attempts = self._failed_attempts[client_ip]
        threshold = now - LOGIN_WINDOW
        while attempts and attempts[0] <= threshold:
            attempts.popleft()
        return attempts
