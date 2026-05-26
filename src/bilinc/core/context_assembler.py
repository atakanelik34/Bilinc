"""Agent-ready context assembly for Bilinc cognitive runtime.

This module is intentionally read-only. It turns existing recall/profile output into
prompt-safe context packets without committing, revising, or capturing eval rows.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


SECTION_TITLES = {
    "active_context": "Active context",
    "stable_facts": "Stable facts",
    "recent_relevant_events": "Recent relevant events",
    "preferences_and_procedures": "Preferences and procedures",
    "spatial_context": "Spatial context",
    "cautions_and_contradictions": "Cautions and contradictions",
}

MEMORY_TYPE_SECTIONS = {
    "working": "active_context",
    "semantic": "stable_facts",
    "episodic": "recent_relevant_events",
    "procedural": "preferences_and_procedures",
    "spatial": "spatial_context",
}

SECTION_ORDER = [
    "stable_facts",
    "active_context",
    "recent_relevant_events",
    "preferences_and_procedures",
    "spatial_context",
    "cautions_and_contradictions",
]

MEMORY_TYPE_RANK = {
    "semantic": 0,
    "working": 1,
    "episodic": 2,
    "procedural": 3,
    "spatial": 4,
}


@dataclass
class ContextSection:
    """A named group of context items for prompt assembly."""

    name: str
    title: str
    items: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "title": self.title, "items": self.items}


@dataclass
class ContextBundle:
    """Read-only context packet suitable for injection into an agent prompt."""

    query: str
    profile: str
    sections: List[ContextSection]
    prompt_block: str
    token_estimate: int
    selected_memory_keys: List[str]
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    omitted_counts: Dict[str, int] = field(default_factory=lambda: {"items": 0, "tokens": 0})
    read_only: bool = True

    def section(self, name: str) -> ContextSection:
        for section in self.sections:
            if section.name == name:
                return section
        raise KeyError(name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "profile": self.profile,
            "sections": [section.to_dict() for section in self.sections],
            "prompt_block": self.prompt_block,
            "token_estimate": self.token_estimate,
            "selected_memory_keys": self.selected_memory_keys,
            "evidence_refs": self.evidence_refs,
            "evidence": self.evidence,
            "warnings": self.warnings,
            "omitted_counts": self.omitted_counts,
            "read_only": self.read_only,
        }


class ContextAssembler:
    """Build deterministic, budgeted context packets from StatePlane recall output."""

    def __init__(self, state_plane: Any):
        self.state_plane = state_plane

    async def assemble(
        self,
        query: str,
        *,
        profile: Optional[str] = None,
        limit: int = 10,
        budget_tokens: int = 4096,
        memory_types: Optional[List[Any]] = None,
    ) -> ContextBundle:
        query = (query or "").strip()
        budget_tokens = max(1, int(budget_tokens))
        profile_name = (profile or "balanced").strip().lower()

        previous_suppression = getattr(self.state_plane, "_suppress_eval_capture", False)
        setattr(self.state_plane, "_suppress_eval_capture", True)
        try:
            payload = await self.state_plane.recall_profiled(
                query,
                profile=profile_name,
                limit=limit,
                memory_types=memory_types,
            )
        finally:
            setattr(self.state_plane, "_suppress_eval_capture", previous_suppression)

        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        results = self._sort_results(raw_results)
        evidence = payload.get("evidence", {"claims": [], "contradictions": {"count": 0, "findings": []}})
        warnings: List[Dict[str, Any]] = []

        sections_by_name = {
            name: ContextSection(name=name, title=SECTION_TITLES[name])
            for name in SECTION_ORDER
        }

        selected_keys: List[str] = []
        evidence_refs: List[Dict[str, Any]] = []
        omitted_items = 0
        omitted_tokens = 0

        for result in results:
            item = self._context_item(result)
            section_name = MEMORY_TYPE_SECTIONS.get(item["memory_type"], "stable_facts")
            candidate_sections = self._copy_sections(sections_by_name)
            candidate_sections[section_name].items.append(item)
            candidate_prompt = self._render_prompt(candidate_sections, warnings)
            candidate_tokens = self._estimate_tokens(candidate_prompt)
            if candidate_tokens <= budget_tokens:
                sections_by_name = candidate_sections
                selected_keys.append(item["key"])
                evidence_refs.append({
                    "memory_key": item["key"],
                    "memory_type": item["memory_type"],
                    "score": item.get("score", 0.0),
                })
                continue
            if not selected_keys:
                truncated = self._truncate_item_to_budget(item, sections_by_name, section_name, warnings, budget_tokens)
                if truncated is not None:
                    sections_by_name[section_name].items.append(truncated)
                    selected_keys.append(truncated["key"])
                    evidence_refs.append({
                        "memory_key": truncated["key"],
                        "memory_type": truncated["memory_type"],
                        "score": truncated.get("score", 0.0),
                    })
                    omitted_tokens += max(0, self._estimate_tokens(item["value"]) - self._estimate_tokens(truncated["value"]))
                    continue
            omitted_items += 1
            omitted_tokens += self._estimate_tokens(self._format_item(item))

        scoped_evidence = self._scope_evidence(evidence, set(selected_keys))
        final_warnings = self._build_warnings(scoped_evidence)
        prompt_block = self._render_prompt(sections_by_name, final_warnings)
        while self._estimate_tokens(prompt_block) > budget_tokens and selected_keys:
            removed = self._remove_last_item(sections_by_name)
            if removed is None:
                break
            selected_keys.remove(removed["key"])
            evidence_refs = [ref for ref in evidence_refs if ref["memory_key"] != removed["key"]]
            omitted_items += 1
            omitted_tokens += self._estimate_tokens(self._format_item(removed))
            scoped_evidence = self._scope_evidence(evidence, set(selected_keys))
            final_warnings = self._build_warnings(scoped_evidence)
            prompt_block = self._render_prompt(sections_by_name, final_warnings)

        sections = [sections_by_name[name] for name in SECTION_ORDER]
        return ContextBundle(
            query=query,
            profile=profile_name,
            sections=sections,
            prompt_block=prompt_block,
            token_estimate=self._estimate_tokens(prompt_block),
            selected_memory_keys=selected_keys,
            evidence_refs=evidence_refs,
            evidence=scoped_evidence,
            warnings=final_warnings,
            omitted_counts={"items": omitted_items, "tokens": omitted_tokens},
            read_only=True,
        )

    def _sort_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            [result for result in results if isinstance(result, dict)],
            key=lambda item: (
                MEMORY_TYPE_RANK.get(str(item.get("memory_type", "semantic")), 99),
                -float(item.get("score") or 0.0),
                str(item.get("key") or ""),
            ),
        )

    def _context_item(self, result: Dict[str, Any]) -> Dict[str, Any]:
        value = result.get("value")
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return {
            "key": str(result.get("key")),
            "memory_type": str(result.get("memory_type", "semantic")),
            "value": " ".join(value.split()),
            "importance": float(result.get("importance") or 0.0),
            "score": float(result.get("score") or 0.0),
            "signals": result.get("signals", {}),
        }

    def _copy_sections(self, sections_by_name: Dict[str, ContextSection]) -> Dict[str, ContextSection]:
        return {
            name: ContextSection(name=section.name, title=section.title, items=list(section.items))
            for name, section in sections_by_name.items()
        }

    def _render_prompt(self, sections_by_name: Dict[str, ContextSection], warnings: List[Dict[str, Any]]) -> str:
        lines = ["# Bilinc Context Packet", "", "Use this as supporting memory, not as absolute truth."]
        for name in SECTION_ORDER:
            section = sections_by_name[name]
            if name == "cautions_and_contradictions":
                if not warnings:
                    continue
                lines.extend(["", f"## {section.title}"])
                for warning in warnings:
                    lines.append(f"- [{warning['type']}] {warning['message']}")
                continue
            if not section.items:
                continue
            lines.extend(["", f"## {section.title}"])
            for item in section.items:
                lines.append(self._format_item(item))
        return "\n".join(lines).strip() + "\n"

    def _format_item(self, item: Dict[str, Any]) -> str:
        value = item.get("value", "")
        return f"- ({item.get('memory_type')}) {item.get('key')}: {value}"

    def _remove_last_item(self, sections_by_name: Dict[str, ContextSection]) -> Optional[Dict[str, Any]]:
        for name in reversed(SECTION_ORDER):
            if name == "cautions_and_contradictions":
                continue
            section = sections_by_name[name]
            if section.items:
                return section.items.pop()
        return None

    def _truncate_item_to_budget(
        self,
        item: Dict[str, Any],
        sections_by_name: Dict[str, ContextSection],
        section_name: str,
        warnings: List[Dict[str, Any]],
        budget_tokens: int,
    ) -> Optional[Dict[str, Any]]:
        words = re.findall(r"\S+", item.get("value", ""))
        for keep in range(len(words), 0, -1):
            truncated = dict(item)
            suffix = " ..." if keep < len(words) else ""
            truncated["value"] = " ".join(words[:keep]) + suffix
            candidate_sections = self._copy_sections(sections_by_name)
            candidate_sections[section_name].items.append(truncated)
            if self._estimate_tokens(self._render_prompt(candidate_sections, warnings)) <= budget_tokens:
                return truncated
        return None

    def _build_warnings(self, evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
        warnings: List[Dict[str, Any]] = []
        contradictions = evidence.get("contradictions", {}) if isinstance(evidence, dict) else {}
        count = int(contradictions.get("count") or 0) if isinstance(contradictions, dict) else 0
        if count:
            warnings.append({
                "type": "contradiction",
                "message": f"{count} contradiction finding(s) in selected recall evidence.",
                "count": count,
            })
        return warnings

    def _scope_evidence(self, evidence: Dict[str, Any], selected_keys: set[str]) -> Dict[str, Any]:
        if not isinstance(evidence, dict):
            return {"claims": [], "contradictions": {"count": 0, "findings": []}}
        claims = [
            claim for claim in evidence.get("claims", [])
            if str(claim.get("memory_key")) in selected_keys
        ]
        raw_contradictions = evidence.get("contradictions", {"count": 0, "findings": []})
        scoped_findings = []
        if isinstance(raw_contradictions, dict):
            for finding in raw_contradictions.get("findings", []):
                finding_keys = {str(key) for key in finding.get("memory_keys", [])}
                if finding_keys and finding_keys.issubset(selected_keys):
                    scoped_findings.append(finding)
        scoped_contradictions = {
            "count": len(scoped_findings),
            "findings": scoped_findings,
        }
        return {
            "claims": claims,
            "contradictions": scoped_contradictions,
        }

    def _estimate_tokens(self, text: str) -> int:
        return len(re.findall(r"[A-Za-z0-9_]+", text or ""))
