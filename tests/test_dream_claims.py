"""Public wording for the dream pass in CHANGELOG.md and README.md."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
METADATA_SENTENCE = (
    "undoing a removed entry restores its value, type, importance and source; other metadata "
    "such as TTL or canonical flags is not restored, so an entry that had a TTL comes back without one"
)
BANNED = (
    "verifies",
    "detects contradictions",
    "only",
    "first",
    "integration",
    "anthropic dreams",
    "karpathy",
    "postgres",
    "sidecar",
    "next.js",
)


def _unreleased_added() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = text.split("## [Unreleased] (2.7.0)", 1)[1].split("\n## [", 1)[0]
    return section.split("### Added", 1)[1].split("\n### ", 1)[0]


def _dream_bullets() -> list[str]:
    bullets = [line for line in _unreleased_added().splitlines() if line.startswith("- ")]
    return [line for line in bullets if re.search(r"\bdream", line, re.IGNORECASE) or "if_absent" in line]


def _banned_in(text: str) -> list[str]:
    lowered = text.lower()
    return [word for word in BANNED if re.search(rf"(?<![\w.]){re.escape(word)}(?![\w])", lowered)]


def test_changelog_dream_entry_follows_claim_rules():
    bullets = _dream_bullets()
    assert bullets, "the Unreleased section must describe the dream pass"
    joined = "\n".join(bullets)

    assert "dream pass" in joined.lower()
    assert "tidy your agent's memory, undo it in one step" in joined.lower()
    assert METADATA_SENTENCE.lower() in joined.lower()
    assert "coming to the hosted connector" in joined
    for needed in ("forget cap", "7 days", "if_absent"):
        assert needed in joined, needed
    assert _banned_in(joined) == []


def test_readme_lists_the_dream_tools_as_stdio_and_coming_to_the_hosted_connector():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    rows = [line for line in readme.splitlines() if line.startswith("| `dream_")]

    assert [row.split("`")[1] for row in rows] == ["dream_start", "dream_apply", "dream_undo"]
    for row in rows:
        assert "stdio adapter; coming to the hosted connector" in row.lower()
        assert _banned_in(row) == []
