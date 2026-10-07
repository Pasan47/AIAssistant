"""Option A: hard-coded users/roles (assumption.docx). Focus is RBAC, not an identity provider."""
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings
from app.errors import AuthError
from app.permissions import Role


@dataclass(frozen=True)
class User:
    username: str
    role: Role
    department: str


# POC ONLY. Production: Keycloak/OIDC, hashed credentials, no secrets in source.
_USERS = {
    "viewer": ("viewer123", Role.VIEWER, "retail"),
    "analyst": ("analyst123", Role.ANALYST, "payments"),
    "admin": ("admin123", Role.ADMIN, "platform"),
}


def authenticate(username: str, password: str) -> User | None:
    record = _USERS.get(username)
    # compare against a dummy when the user is unknown to keep timing uniform
    expected = record[0] if record else "x" * 16
    ok = hmac.compare_digest(password.encode(), expected.encode())
    if not (record and ok):
        return None
    return User(username, record[1], record[2])


def issue_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_ttl_minutes)
    return jwt.encode({"sub": user.username, "exp": exp}, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> User:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthError() from exc
    record = _USERS.get(claims.get("sub", ""))
    if not record:
        raise AuthError()
    # role is re-derived server-side; we never trust a role claim from the client
    return User(claims["sub"], record[1], record[2])
