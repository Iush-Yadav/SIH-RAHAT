"""Authentication and RBAC.

Deliberately dependency-free: HS256 JWT and PBKDF2-HMAC-SHA256 are both about
ten lines with the standard library, and both are genuine, standards-compliant
implementations. That keeps the deployable image small and avoids pulling a
crypto transitive tree into an air-gapped build.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from .config import settings

ROLES = {
    "commander": {
        "label": "Formation Commander",
        "can": ["view", "simulate", "approve", "briefing"],
    },
    "logistics_officer": {
        "label": "Logistics Officer",
        "can": ["view", "simulate", "plan", "briefing"],
    },
    "quartermaster": {
        "label": "Quartermaster",
        "can": ["view", "inventory", "acknowledge"],
    },
    "admin": {
        "label": "System Administrator",
        "can": ["view", "simulate", "plan", "inventory", "acknowledge",
                "briefing", "admin", "retrain"],
    },
}


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# JWT (HS256)
# --------------------------------------------------------------------------- #
def _b64(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_token(username: str, role: str, ttl_s: int | None = None) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": username, "role": role, "iat": now,
        "exp": now + (ttl_s if ttl_s is not None else settings.jwt_ttl_s),
        "iss": "rahat",
    }
    signing = _b64(json.dumps(header, separators=(",", ":")).encode()) + b"." + \
        _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(settings.jwt_secret.encode(), signing, hashlib.sha256).digest()
    return (signing + b"." + _b64(sig)).decode()


def decode_token(token: str) -> dict[str, Any] | None:
    """Returns the payload, or None when missing/expired/tampered."""
    try:
        head, body, sig = token.split(".")
        header = json.loads(_unb64(head))
        if not isinstance(header, dict) or header.get("alg") != "HS256":
            return None
        signing = f"{head}.{body}".encode()
        expected = hmac.new(settings.jwt_secret.encode(), signing, hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(sig), expected):
            return None
        payload = json.loads(_unb64(body))
        if not isinstance(payload, dict):
            return None
        if not isinstance(payload.get("exp"), (int, float)) or payload["exp"] <= time.time():
            return None
        if payload.get("iss") != "rahat" or not isinstance(payload.get("sub"), str):
            return None
        if not payload["sub"] or payload.get("role") not in ROLES:
            return None
        return payload
    except (ValueError, TypeError, UnicodeError):
        return None


def permissions(role: str) -> list[str]:
    return list(ROLES.get(role, {}).get("can", ["view"]))
