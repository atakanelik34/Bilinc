"""Deterministic claim projection utilities."""

from __future__ import annotations

import hashlib
from typing import Any

from bilinc.core.models import Claim, ClaimKind, MemoryEntry


def normalize_claim_kind(value: Any) -> ClaimKind | None:
    try:
        return ClaimKind(str(value).strip().lower())
    except (ValueError, TypeError):
        return None


def claim_id_for(memory_key: str, claim_text: str, holder: str, subject: str) -> str:
    material = "\x1f".join([
        str(memory_key).strip(),
        str(holder).strip().lower(),
        str(subject).strip().lower(),
        str(claim_text).strip().lower(),
    ])
    return "claim_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _claim_from_mapping(memory_key: str, data: dict[str, Any], source: str = "") -> Claim | None:
    kind = normalize_claim_kind(data.get("kind", ClaimKind.FACT.value))
    if kind is None:
        return None
    holder = str(data.get("holder") or "").strip()
    subject = str(data.get("subject") or data.get("entity") or "").strip()
    claim_text = str(data.get("claim") or data.get("text") or "").strip()
    if not holder or not subject or not claim_text:
        return None
    raw_metadata = data.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        return None
    return Claim(
        memory_key=memory_key,
        holder=holder,
        subject=subject,
        claim=claim_text,
        kind=kind,
        confidence=confidence,
        valid_at=data.get("valid_at"),
        invalid_at=data.get("invalid_at"),
        source=str(data.get("source") or source or ""),
        provenance_id=str(data.get("provenance_id") or memory_key),
        active=bool(data.get("active", True)),
        superseded_by=data.get("superseded_by"),
        metadata=metadata,
    )


def extract_claims_from_entry(entry: MemoryEntry) -> list[Claim]:
    """Extract only explicit structured claims. No freeform/LLM extraction."""
    claims: list[Claim] = []
    seen: set[str] = set()

    raw_claims = (entry.metadata or {}).get("claims", [])
    if isinstance(raw_claims, dict):
        raw_claims = [raw_claims]
    if isinstance(raw_claims, list):
        for item in raw_claims:
            if not isinstance(item, dict):
                continue
            claim = _claim_from_mapping(entry.key, item, source=entry.source)
            if claim and claim.id not in seen:
                seen.add(claim.id)
                claims.append(claim)

    if isinstance(entry.value, dict) and "claim" in entry.value:
        claim = _claim_from_mapping(entry.key, entry.value, source=entry.source)
        if claim and claim.id not in seen:
            claims.append(claim)

    return claims
