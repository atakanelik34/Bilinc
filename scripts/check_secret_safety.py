"""Fail closed on likely credential material in tracked text files.

The checker intentionally reports only file paths and rule identifiers, never a
matched value, so CI logs remain safe to share.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
RULES = {
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "stripe-secret": re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    "cloudflare-token": re.compile(r"\b(?:CF_API_TOKEN|CLOUDFLARE_API_TOKEN)\s*=\s*[^\s#]{16,}"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
FIXTURE_ONLY_PATHS = {
    Path("tests/test_eval_capture.py"),
    Path("tests/test_knowledge_graph.py"),
}


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [ROOT / item.decode() for item in output.split(b"\0") if item]


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        if not path.is_file() or path.stat().st_size > 1_000_000:
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        relative_path = path.relative_to(ROOT)
        if relative_path in FIXTURE_ONLY_PATHS:
            continue
        text = data.decode("utf-8", errors="ignore")
        for name, pattern in RULES.items():
            if pattern.search(text):
                findings.append(f"{relative_path}: {name}")
    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("Secret safety check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
