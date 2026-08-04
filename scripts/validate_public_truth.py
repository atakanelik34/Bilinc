"""Validate the public Bilinc truth manifest against the shipped Cloud package."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.10 public support
    import tomli as tomllib


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "docs" / "public" / "product-truth.json"
REQUIRED_TOP_LEVEL = {
    "schema_version",
    "canonical_repository",
    "source_commit",
    "verified_at",
    "package",
    "cloud_mcp",
    "public_urls",
    "benchmark_claims",
    "boundary",
}
REQUIRED_PACKAGE_FIELDS = {"name", "version", "requires_python", "license", "install", "exports"}
FORBIDDEN_PUBLIC_TERMS = {
    "postgres",
    "sqlite",
    "nginx",
    "pm2",
    "sidecar",
    "internal token",
    "admin endpoint",
}


def _cloud_mcp_tool_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    tools: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "tool"
            for decorator in node.decorator_list
        ):
            tools.append(node.name)
    return tools


def validate_product_truth(path: Path = MANIFEST) -> list[str]:
    """Return all manifest/code contract violations without exposing sensitive values."""
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read public truth manifest: {exc}"]

    errors = [f"missing top-level field: {field}" for field in sorted(REQUIRED_TOP_LEVEL - payload.keys())]
    if errors:
        return errors

    package = payload["package"]
    if not isinstance(package, dict):
        return ["package must be an object"]
    errors.extend(f"missing package field: {field}" for field in sorted(REQUIRED_PACKAGE_FIELDS - package.keys()))
    if errors:
        return errors

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    if package["name"] != project["name"]:
        errors.append("package name does not match pyproject.toml")
    if package["version"] != project["version"]:
        errors.append("package version does not match pyproject.toml")
    if package["requires_python"] != project["requires-python"]:
        errors.append("Python support range does not match pyproject.toml")
    if package["license"] != project["license"]:
        errors.append("license does not match pyproject.toml")

    sys.path.insert(0, str(ROOT / "src"))
    import bilinc  # noqa: PLC0415

    exports = set(package["exports"])
    actual_exports = set(bilinc.__all__) - {
        "ACTIVATION_SIGNUP_URL",
        "DEFAULT_BASE_URL",
        "INSTALL_URL",
        "SIGNUP_URL",
        "__version__",
        "version",
    }
    if exports != actual_exports:
        errors.append("public exports do not match bilinc.__all__")

    tools = payload["cloud_mcp"].get("tools", []) if isinstance(payload["cloud_mcp"], dict) else []
    if tools != _cloud_mcp_tool_names(ROOT / "src" / "bilinc" / "cloud_mcp.py"):
        errors.append("Cloud MCP tools do not match cloud_mcp.py")
    benchmark = payload["benchmark_claims"]
    required_benchmark_fields = {"state", "public_approved", "label", "scope", "metrics", "qualification", "rule"}
    errors.extend(
        f"missing benchmark field: {field}"
        for field in sorted(required_benchmark_fields - benchmark.keys())
    )
    if benchmark.get("state") != "historical_scoped":
        errors.append("benchmark state must remain historical and scoped")
    if benchmark.get("public_approved") is not True:
        errors.append("archived benchmark receipt must be explicitly public-approved")
    if benchmark.get("label") != "Frozen regression receipt":
        errors.append("benchmark label must identify the result as a frozen regression receipt")
    if benchmark.get("scope") != "LongMemEval-s cleaned retrieval fixture, 500 questions":
        errors.append("benchmark scope must preserve the fixture boundary")
    if benchmark.get("metrics") != {"hit_at_5": "98.0%", "ndcg_at_5": "0.913"}:
        errors.append("benchmark metrics must match the scoped frozen receipt")
    qualification = benchmark.get("qualification", "")
    if not isinstance(qualification, str) or "not a current hosted SLA" not in qualification:
        errors.append("benchmark qualification must rule out current hosted SLA claims")

    serialized = json.dumps(payload).lower()
    errors.extend(f"public truth contains forbidden internal term: {term}" for term in FORBIDDEN_PUBLIC_TERMS if term in serialized)
    return errors


def main() -> int:
    errors = validate_product_truth()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Validated public product truth contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
