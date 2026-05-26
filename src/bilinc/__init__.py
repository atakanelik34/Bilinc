"""Bilinc 2.1.1: cloud-only SDK for agent memory."""

from bilinc.client import (
    DEFAULT_BASE_URL,
    SIGNUP_URL,
    Bilinc,
    BilincApiKeyRequired,
    BilincCloudError,
    BilincError,
    CloudClient,
)

__version__ = "2.1.1"
version = __version__

__all__ = [
    "Bilinc",
    "BilincApiKeyRequired",
    "BilincCloudError",
    "BilincError",
    "CloudClient",
    "DEFAULT_BASE_URL",
    "SIGNUP_URL",
    "__version__",
    "version",
]
