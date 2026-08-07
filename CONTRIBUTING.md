# Contributing to Bilinc

Bilinc is a verifiable state plane for autonomous agents. Contributions are welcome when they improve a general
memory capability, its safety boundary, its developer experience, or its reproducibility.

## Before opening a change

1. Search existing issues and Discussions.
2. For a design change, start a Discussion before writing a large implementation.
3. Keep benchmark adapters and fixtures outside the product-core path.
4. Never add benchmark-query aliases, expected-answer strings, query-specific bonuses, or answer caches.
5. Never include API keys, private memory values, production logs, or customer data.

## Local verification

```bash
python3 -m pytest tests/ -q
python3 -m ruff check src tests benchmarks
python3 -m build
python3 -m benchmarks.validate_evidence
```

Run the smallest relevant focused test first. If a retrieval or state change could affect a frozen benchmark guardrail,
record the protocol and dataset hashes and explain the scope of the result.

## Pull requests

- Explain the user-visible capability and the failure it addresses.
- Add a focused test and, where useful, a neutral or metamorphic test.
- Preserve SQLite/PostgreSQL and public SDK/MCP compatibility.
- Include benchmark evidence only with its exact lane, metric, dataset, protocol, and limitations.
- Keep claims proportional to reproducible evidence. Do not call a result SOTA or #1 without matched external proof.

## Questions and support

Use [GitHub Discussions](https://github.com/atakanelik34/Bilinc/discussions) for architecture and roadmap questions.
Use an issue for a reproducible bug or a narrowly scoped feature request.
