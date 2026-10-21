"""Secret scanning for hosted memory writes.

Two kinds of finding, kept apart on purpose:

* Provider-shaped credentials (a fixed prefix plus a length floor, such as an
  AWS access key ID or a GitHub token) are near-certain secrets. A write that
  contains one is rejected and nothing is stored.
* Field-name hits (``password=...``, ``Authorization: Bearer ...``, a dict key
  such as ``api_key``) are likely secrets. Their value is replaced with
  ``[REDACTED]`` and the write goes ahead with a warning.

Entropy alone never rejects. Findings name the rule and the field, never the
matched text. The rule shapes are public provider formats, written for Bilinc
in the style of gitleaks' prefix-plus-keyword rules.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

REDACTED = "[REDACTED]"

# (rule id, lowercase keywords that must appear before the regex runs, regex)
_SHAPE_RULES = [
    ("aws_access_key", ("akia", "asia"), re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"), re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("github_token", ("github_pat_",), re.compile(r"\bgithub_pat_[A-Za-z0-9_]{70,}")),
    ("gitlab_token", ("glpat-",), re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("slack_token", ("xox", "xapp-"), re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}|\bxapp-\d-[A-Za-z0-9-]{10,}")),
    ("stripe_live_key", ("sk_live_", "rk_live_"), re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,}")),
    ("anthropic_api_key", ("sk-ant-",), re.compile(r"\bsk-ant-[a-z]+\d{2}-[A-Za-z0-9_-]{40,}")),
    (
        "openai_api_key",
        ("sk-",),
        re.compile(r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{40,}|\bsk-[A-Za-z0-9]{40,}"),
    ),
    ("google_api_key", ("aiza",), re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("pypi_token", ("pypi-",), re.compile(r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{50,}")),
    ("bilinc_key", ("bil_",), re.compile(r"\bbil_(?:live|oat|ort|oac|inv)_[A-Za-z0-9_-]{20,}")),
    (
        "jwt",
        ("eyj",),
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ),
    ("private_key", ("private key",), re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
]

_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pwd|passphrase|secret|client[_-]?secret|api[_-]?key|access[_-]?key|"
    r"access[_-]?token|auth[_-]?token|refresh[_-]?token|private[_-]?key|token)\b"
    r"([\"']?\s*[:=]\s*)([\"']?)([^\s\"',;]{8,})"
)
_AUTH_HEADER = re.compile(r"(?i)\b(bearer|basic)(\s+)([A-Za-z0-9._~+/=-]{16,})")
_FIELD_KEYWORDS = ("pass", "secret", "key", "token", "bearer", "basic", "pwd", "credential")

_SENSITIVE_KEY_SUFFIXES = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "access_token",
    "auth_token",
    "refresh_token",
    "token",
    "credential",
    "credentials",
)
_DOCUMENTATION_VALUE = re.compile(r"(?i)example|xxxx|your|dummy|placeholder|redacted|(.)\1{11,}")
_PLACEHOLDER = re.compile(
    r"(?i)^(?:\*+|x+|\.+|-+|#+|(.)\1+|null|none|true|false|changeme|redacted|\[redacted\]|"
    r".*(?:\$\{|\{\{|<[^>]*>|your[_-]|example|placeholder|dummy|sample).*)$"
)


@dataclass(frozen=True)
class SecretFinding:
    rule: str
    field: str


@dataclass
class ScanResult:
    rejection: Optional[SecretFinding] = None
    redactions: list[SecretFinding] = field(default_factory=list)
    value: Any = None
    metadata: Any = None
    reason: Optional[str] = None


def scanning_enabled() -> bool:
    """``BILINC_SECRET_SCAN=off`` turns the scan off (read on every write)."""
    return os.getenv("BILINC_SECRET_SCAN", "on").strip().lower() not in {"off", "0", "false", "no"}


def _is_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER.match(text))


def _looks_like_credential(text: str) -> bool:
    """A free-text value after ``password:``/``Bearer`` is redacted only if it looks generated.

    Prose and paths (``Basic setup/teardown``, ``Token: ~/.config/...``,
    ``password: Configured``) stay readable: the value must mix letters with
    digits, or be long and mixed-case, and must not be a path.
    """
    if _is_placeholder(text) or text.startswith(("/", "~", "./", "../")) or text.count("/") >= 2:
        return False
    has_letter = any(c.isalpha() for c in text)
    has_digit = any(c.isdigit() for c in text)
    mixed_case = any(c.isupper() for c in text) and any(c.islower() for c in text)
    return (has_letter and has_digit) or (len(text) >= 24 and mixed_case)


def _is_documentation_value(match: str) -> bool:
    """Published example keys (``...EXAMPLE``), ``xxxx`` fillers and long single-character runs."""
    return bool(_DOCUMENTATION_VALUE.search(match))


def find_secret_shape(text: str) -> Optional[str]:
    """Return the rule id of the first provider-shaped credential in ``text``."""
    lowered = text.lower()
    for rule, keywords, pattern in _SHAPE_RULES:
        if not any(keyword in lowered for keyword in keywords):
            continue
        if any(not _is_documentation_value(match.group(0)) for match in pattern.finditer(text)):
            return rule
    return None


def _first_shape(value: Any, path: str) -> Optional[SecretFinding]:
    if isinstance(value, str):
        rule = find_secret_shape(value)
        return SecretFinding(rule, path) if rule else None
    if isinstance(value, dict):
        for item_key, item in value.items():
            found = _first_shape(str(item_key), path) or _first_shape(item, f"{path}.{item_key}")
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = _first_shape(item, f"{path}[{index}]")
            if found:
                return found
    return None


def _redact_text(text: str, path: str, redactions: list[SecretFinding]) -> str:
    lowered = text.lower()
    if not any(keyword in lowered for keyword in _FIELD_KEYWORDS):
        return text

    def assignment(match: re.Match) -> str:
        if not _looks_like_credential(match.group(4)):
            return match.group(0)
        redactions.append(SecretFinding("credential_assignment", path))
        return f"{match.group(1)}{match.group(2)}{match.group(3)}{REDACTED}"

    def header(match: re.Match) -> str:
        if not _looks_like_credential(match.group(3)):
            return match.group(0)
        redactions.append(SecretFinding("authorization_header", path))
        return f"{match.group(1)}{match.group(2)}{REDACTED}"

    return _AUTH_HEADER.sub(header, _ASSIGNMENT.sub(assignment, text))


def _is_sensitive_key(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return any(normalized == suffix or normalized.endswith("_" + suffix) for suffix in _SENSITIVE_KEY_SUFFIXES)


def _redact(value: Any, path: str, redactions: list[SecretFinding]) -> Any:
    if isinstance(value, str):
        return _redact_text(value, path, redactions)
    if isinstance(value, dict):
        redacted = {}
        for item_key, item in value.items():
            item_path = f"{path}.{item_key}"
            if (
                isinstance(item, str)
                and len(item) >= 8
                and _is_sensitive_key(str(item_key))
                and not any(c.isspace() for c in item)
                and _looks_like_credential(item)
            ):
                redactions.append(SecretFinding("sensitive_field", item_path))
                redacted[item_key] = REDACTED
            else:
                redacted[item_key] = _redact(item, item_path, redactions)
        return redacted
    if isinstance(value, list):
        return [_redact(item, f"{path}[{index}]", redactions) for index, item in enumerate(value)]
    if isinstance(value, tuple):
        return tuple(_redact(item, f"{path}[{index}]", redactions) for index, item in enumerate(value))
    return value


def _mask_shapes(value: Any, path: str, findings: list[SecretFinding]) -> Any:
    if isinstance(value, str):
        lowered = value.lower()
        for rule, keywords, pattern in _SHAPE_RULES:
            if not any(keyword in lowered for keyword in keywords):
                continue

            def mask(match: re.Match, rule: str = rule) -> str:
                if _is_documentation_value(match.group(0)):
                    return match.group(0)
                findings.append(SecretFinding(rule, path))
                return REDACTED

            value = pattern.sub(mask, value)
        return value
    if isinstance(value, dict):
        masked = {}
        for item_key, item in value.items():
            # The path never carries the raw key: it may be the secret itself.
            key_text = _mask_shapes(str(item_key), f"{path}.<key>", findings)
            masked[key_text] = _mask_shapes(item, f"{path}.{key_text}", findings)
        return masked
    if isinstance(value, (list, tuple)):
        masked = [_mask_shapes(item, f"{path}[{index}]", findings) for index, item in enumerate(value)]
        return masked if isinstance(value, list) else tuple(masked)
    return value


def scrub_note(value: Any, field: str = "reason") -> tuple[Any, list[SecretFinding]]:
    """Mask secrets in an operator note without ever refusing the operation.

    Used for the reasons of ``forget``, ``confirm`` and ``rollback`` and for
    snapshot labels and metadata: those operations must always work (a secret
    must stay removable), so provider-shaped matches are masked rather than
    rejected, then credential fields are redacted as usual.
    """
    if value is None or value == "":
        return value, []
    findings: list[SecretFinding] = []
    masked = _mask_shapes(value, field, findings)
    return _redact(masked, field, findings), findings


def scan_write(
    *,
    key: str,
    value: Any,
    metadata: Any = None,
    reason: Optional[str] = None,
    labels: Optional[dict[str, Any]] = None,
) -> ScanResult:
    """Check one memory write. A rejection wins; otherwise return redacted copies.

    ``labels`` are short stored fields such as ``source`` and ``session_id``:
    they are checked for provider-shaped secrets but never rewritten.
    """
    fields = [(key, "key"), (value, "value"), (metadata, "metadata"), (reason, "reason")]
    fields.extend((item, name) for name, item in (labels or {}).items())
    for item, path in fields:
        found = _first_shape(item, path)
        if found:
            return ScanResult(rejection=found, value=value, metadata=metadata, reason=reason)
    redactions: list[SecretFinding] = []
    return ScanResult(
        redactions=redactions,
        value=_redact(value, "value", redactions),
        metadata=_redact(metadata, "metadata", redactions),
        reason=_redact(reason, "reason", redactions) if reason is not None else None,
    )
