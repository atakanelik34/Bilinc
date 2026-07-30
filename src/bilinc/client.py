"""Bilinc Cloud client.

Bilinc 2.1.5 is cloud-only: the PyPI package is a thin SDK and MCP adapter for
https://bilinc.space. Local self-hosted StatePlane internals are no longer
shipped in the public package.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

__version__ = "2.1.5"
DEFAULT_BASE_URL = "https://bilinc.space"
SIGNUP_URL = "https://bilinc.space/signup"
ACTIVATION_CAMPAIGN = "activation_2_1_3"
ACTIVATION_SIGNUP_URL = (
    f"{SIGNUP_URL}?utm_source=pypi&utm_medium=cli&utm_campaign={ACTIVATION_CAMPAIGN}"
)
INSTALL_URL = (
    f"{DEFAULT_BASE_URL}/install?utm_source=pypi&utm_medium=cli&utm_campaign={ACTIVATION_CAMPAIGN}"
)
CONFIG_DIR_ENV = "BILINC_CONFIG_DIR"
CONFIG_FILE_NAME = "config.json"


API_VERSION = "2026-07-30"

#: Canonical public error code -> HTTP status. Every Bilinc Cloud failure the
#: SDK surfaces maps onto exactly one of these codes, so callers can branch on
#: "authenticate / upgrade / retry / resolve conflict / fix input" without
#: parsing free-form English.
CANONICAL_ERROR_CODES: dict[str, int] = {
    "missing_api_key": 401,
    "invalid_api_key": 401,
    "entitlement_inactive": 403,
    "capability_not_entitled": 403,
    "payment_required": 402,
    "invalid_request": 400,
    "memory_not_found": 404,
    "snapshot_not_found": 404,
    "version_conflict": 409,
    "idempotency_conflict": 409,
    "state_changed_since_preview": 409,
    "rollback_confirmation_expired": 410,
    "rate_limited": 429,
    "cloud_runtime_unavailable": 503,
}

RETRYABLE_ERROR_CODES = frozenset({"rate_limited", "cloud_runtime_unavailable", "connection_failed"})


class BilincError(RuntimeError):
    """Base Bilinc SDK error."""


class BilincApiKeyRequired(BilincError):
    """Raised when no Bilinc Cloud API key is configured."""


class BilincCloudError(BilincError):
    """Raised when Bilinc Cloud rejects or fails a request.

    Every typed error below subclasses this, so existing ``except
    BilincCloudError`` handlers keep working unchanged.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        request_id: str | None = None,
        retryable: bool = False,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.request_id = request_id
        self.retryable = retryable
        self.details = details


class BilincValidationError(BilincCloudError):
    """The request was rejected as invalid. Fix the input and try again."""


class BilincAuthError(BilincCloudError):
    """The API key is missing, invalid, revoked, or expired."""


class BilincPaymentRequiredError(BilincCloudError):
    """Included credits are exhausted and no Cloud credits remain."""


class BilincEntitlementError(BilincCloudError):
    """The plan does not entitle this capability."""


class BilincNotFoundError(BilincCloudError):
    """The memory or snapshot does not exist in this project."""


class BilincConflictError(BilincCloudError):
    """Optimistic concurrency, idempotency, or preview state conflict."""


class BilincConfirmationExpiredError(BilincCloudError):
    """A rollback confirmation token expired before it was used."""


class BilincRateLimitError(BilincCloudError):
    """The request was rate limited. Retry after a backoff."""


class BilincRuntimeUnavailableError(BilincCloudError):
    """The hosted memory runtime is temporarily unavailable."""


class BilincConnectionError(BilincCloudError):
    """The Bilinc Cloud endpoint could not be reached."""


_STATUS_ERRORS: dict[int, type[BilincCloudError]] = {
    400: BilincValidationError,
    401: BilincAuthError,
    402: BilincPaymentRequiredError,
    403: BilincEntitlementError,
    404: BilincNotFoundError,
    409: BilincConflictError,
    410: BilincConfirmationExpiredError,
    429: BilincRateLimitError,
    503: BilincRuntimeUnavailableError,
}


def error_for_response(status: int, payload: Any) -> BilincCloudError:
    """Translate a Cloud error response into the matching typed SDK error."""

    body = payload if isinstance(payload, dict) else {}
    code = body.get("error") if isinstance(body.get("error"), str) else None
    message = body.get("message") if isinstance(body.get("message"), str) else None
    request_id = body.get("requestId") if isinstance(body.get("requestId"), str) else None
    retryable = body.get("retryable")
    if not isinstance(retryable, bool):
        retryable = status in (429, 503) or status >= 500 or code in RETRYABLE_ERROR_CODES

    error_class = _STATUS_ERRORS.get(status, BilincCloudError)
    text = message or code or f"HTTP {status}"
    return error_class(
        f"Bilinc Cloud request failed: {text}",
        code=code,
        status=status,
        request_id=request_id,
        retryable=retryable,
        details=body.get("details"),
    )


Transport = Callable[..., dict[str, Any]]


def _default_ssl_context() -> ssl.SSLContext:
    """Return a CA-backed TLS context for Bilinc Cloud requests.

    Some macOS Python installs do not populate OpenSSL's default CA file, which
    makes stdlib urllib fail with CERTIFICATE_VERIFY_FAILED even when the
    system browser and curl can reach bilinc.space. certifi gives the public SDK
    a stable Mozilla CA bundle while still allowing explicit SSL_CERT_FILE or
    BILINC_CA_BUNDLE overrides for locked-down enterprise environments.
    """

    ca_bundle = os.environ.get("BILINC_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if ca_bundle:
        return ssl.create_default_context(cafile=ca_bundle)

    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()

    return ssl.create_default_context(cafile=certifi.where())


def config_path() -> Path:
    """Return the local Bilinc CLI config path."""

    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override).expanduser() / CONFIG_FILE_NAME
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "bilinc" / CONFIG_FILE_NAME
    return Path.home() / ".config" / "bilinc" / CONFIG_FILE_NAME


def load_config() -> dict[str, Any]:
    """Load local CLI config without raising on missing or malformed files."""

    path = config_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_config_api_key() -> str | None:
    """Return a stored API key if one was saved with `bilinc login`."""

    value = load_config().get("api_key")
    return value if isinstance(value, str) and value.strip() else None


def save_config_api_key(api_key: str, *, base_url: str = DEFAULT_BASE_URL) -> Path:
    """Persist the Cloud API key for local CLI use with user-only permissions."""

    key = api_key.strip()
    if not key:
        raise BilincApiKeyRequired(
            "Bilinc requires a Bilinc Cloud API key. "
            f"Start a 7-day trial at {ACTIVATION_SIGNUP_URL}, "
            "then run bilinc login --api-key <key> and bilinc quicktest."
        )

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"api_key": key, "base_url": base_url.rstrip("/") or DEFAULT_BASE_URL}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _default_transport(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(  # noqa: S310 - configured endpoint
            request,
            timeout=timeout,
            context=_default_ssl_context(),
        ) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(detail) if detail else {}
        except json.JSONDecodeError:
            payload = {}
        raise error_for_response(exc.code, payload) from exc
    except urllib.error.URLError as exc:
        raise BilincConnectionError(
            f"Bilinc Cloud request failed: {exc.reason}",
            code="connection_failed",
            retryable=True,
        ) from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BilincCloudError(
            "Bilinc Cloud returned invalid JSON",
            code="invalid_response",
        ) from exc


@dataclass(slots=True)
class CloudClient:
    """Minimal Bilinc Cloud SDK client."""

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 30.0
    transport: Callable[..., dict[str, Any]] = _default_transport

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("BILINC_API_KEY") or load_config_api_key()
        if not self.api_key:
            raise BilincApiKeyRequired(
                "Bilinc requires a Bilinc Cloud API key. "
                f"Start a 7-day trial at {ACTIVATION_SIGNUP_URL}, "
                "then run bilinc login --api-key <key> and bilinc quicktest."
            )
        if self.base_url == DEFAULT_BASE_URL:
            self.base_url = os.environ.get("BILINC_BASE_URL", self.base_url)
        self.base_url = self.base_url.rstrip("/")

    def commit(
        self,
        key: str,
        value: Any,
        *,
        memory_type: str = "semantic",
        importance: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Commit a memory entry to Bilinc Cloud."""

        return self._post(
            "/api/cloud/memory/commit",
            {
                "key": key,
                "value": value,
                "memoryType": memory_type,
                "importance": importance,
                "metadata": metadata or {},
            },
        )

    def recall(
        self,
        query: str,
        *,
        profile: str = "balanced",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Recall memories from Bilinc Cloud."""

        return self._post(
            "/api/cloud/memory/recall",
            {"query": query, "profile": profile, "limit": limit},
        )

    def status(self) -> dict[str, Any]:
        """Return authenticated workspace, plan, capability, and runtime status.

        This answers "what can this API key do?". For "is the service
        reachable?" use :meth:`health`, which needs no authorization.
        """

        return self._get("/api/cloud/status")

    def health(self) -> dict[str, Any]:
        """Return public Bilinc Cloud service health."""

        return self._get("/api/cloud/health")

    def _headers(
        self,
        *,
        content_type: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"bilinc-python/{__version__}",
        }
        if content_type:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return self.transport(
            "POST",
            f"{self.base_url}{path}",
            headers=self._headers(content_type=True, idempotency_key=idempotency_key),
            body=body,
            timeout=float(self.timeout),
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {name: value for name, value in (params or {}).items() if value is not None}
        )
        url = f"{self.base_url}{path}?{query}" if query else f"{self.base_url}{path}"
        return self.transport(
            "GET",
            url,
            headers=self._headers(),
            body=None,
            timeout=float(self.timeout),
        )


Bilinc = CloudClient


__all__ = [
    "ACTIVATION_SIGNUP_URL",
    "API_VERSION",
    "Bilinc",
    "BilincApiKeyRequired",
    "BilincAuthError",
    "BilincCloudError",
    "BilincConfirmationExpiredError",
    "BilincConflictError",
    "BilincConnectionError",
    "BilincEntitlementError",
    "BilincError",
    "BilincNotFoundError",
    "BilincPaymentRequiredError",
    "BilincRateLimitError",
    "BilincRuntimeUnavailableError",
    "BilincValidationError",
    "CANONICAL_ERROR_CODES",
    "CloudClient",
    "DEFAULT_BASE_URL",
    "error_for_response",
    "config_path",
    "INSTALL_URL",
    "load_config_api_key",
    "RETRYABLE_ERROR_CODES",
    "save_config_api_key",
    "SIGNUP_URL",
]
