"""OAuth2 + JWT authentication and RBAC (spec §8 Security).

Partial implementation per scope: OAuth2 password flow → JWT bearer tokens, with
role-based access control on sensitive actions (the underwriter's recorded
decision). MFA, AES-256 at rest, and Kubernetes are documented as deployment-
future (see README). Demo users are in-process; production would back these with
the users table + an IdP.

Roles: underwriter (records decisions), fraud_analyst (reviews escalations),
admin (full access).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

JWT_SECRET = os.environ.get("JWT_SECRET", "trustlens-dev-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
TOKEN_TTL_MINUTES = 60 * 8

# pbkdf2_sha256 — pure-python in passlib, avoids the bcrypt-4.x version shim issue.
_pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=True)

# Demo users (production: users table + IdP). Default password: "trustlens".
DEMO_USERS: dict[str, dict] = {
    "underwriter": {"password_hash": _pwd.hash("trustlens"), "role": "underwriter"},
    "analyst": {"password_hash": _pwd.hash("trustlens"), "role": "fraud_analyst"},
    "admin": {"password_hash": _pwd.hash("trustlens"), "role": "admin"},
}


def authenticate(username: str, password: str) -> dict | None:
    user = DEMO_USERS.get(username)
    if not user or not _pwd.verify(password, user["password_hash"]):
        return None
    return {"username": username, "role": user["role"]}


def create_access_token(username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES)
    return jwt.encode({"sub": username, "role": role, "exp": expire},
                      JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return {"username": payload["sub"], "role": payload.get("role")}
    except (JWTError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})


def require_role(*roles: str):
    """Dependency: requires a valid token AND (if roles given) a matching role."""
    def _dep(user: dict = Depends(get_current_user)) -> dict:
        if roles and user.get("role") not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"Requires role: {', '.join(roles)}")
        return user
    return _dep
