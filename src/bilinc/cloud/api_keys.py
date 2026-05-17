"""API-key issuance and verification helpers for Bilinc Cloud."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass


API_KEY_PREFIX = "bil_live_"
API_KEY_SECRET_BYTES = 24


@dataclass(frozen=True)
class ApiKeyMaterial:
    """One-time API-key material returned at issuance time."""

    raw_key: str
    prefix: str
    secret_hash: str


def generate_api_key() -> ApiKeyMaterial:
    """Generate a one-time raw key plus persisted metadata."""
    secret = secrets.token_urlsafe(API_KEY_SECRET_BYTES)
    raw_key = f"{API_KEY_PREFIX}{secret}"
    visible_prefix = raw_key[:16]
    return ApiKeyMaterial(raw_key=raw_key, prefix=visible_prefix, secret_hash=hash_api_key(raw_key))


def hash_api_key(raw_key: str) -> str:
    """Hash an API key for at-rest storage."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def verify_api_key(raw_key: str, expected_hash: str) -> bool:
    """Constant-time verification against a persisted hash."""
    return hmac.compare_digest(hash_api_key(raw_key), expected_hash)
