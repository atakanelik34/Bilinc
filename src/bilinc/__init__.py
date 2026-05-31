"""Bilinc 2.1.3: cloud-only SDK for agent memory."""

from bilinc.client import (
    ACTIVATION_SIGNUP_URL,
    DEFAULT_BASE_URL,
    INSTALL_URL,
    SIGNUP_URL,
    Bilinc,
    BilincApiKeyRequired,
    BilincCloudError,
    BilincError,
    CloudClient,
)

__version__ = "2.1.3"
version = __version__

__all__ = [
    "Bilinc",
    "BilincApiKeyRequired",
    "BilincCloudError",
    "BilincError",
    "CloudClient",
    "ACTIVATION_SIGNUP_URL",
    "DEFAULT_BASE_URL",
    "INSTALL_URL",
    "SIGNUP_URL",
    "__version__",
    "version",
]
