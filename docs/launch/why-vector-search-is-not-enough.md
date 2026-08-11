# Why vector search is not enough for AI agent memory

Bilinc is a state layer for coding agents. This note explains the problem it is designed to solve and the evidence
boundaries behind the current `2.2.0` release.

## The gap

Vector search is useful for finding text that resembles a query. An agent memory layer has to answer harder questions:

- Is this the current value or a superseded one?
- Who or what produced the memory?
- Is the evidence in the agent's allowed scope?
- What should happen when two memories conflict?
- Can an operator correct or roll back a bad write?

Similarity is a retrieval signal. It is not provenance, belief revision, authorization, or recovery.

## What Bilinc adds

Bilinc keeps those concerns around the memory lifecycle:

1. `commit_mem` records durable state with a key and memory type.
2. `recall` retrieves state through explicit profiles and bounded evidence scope.
3. `revise` makes correction distinguishable from an accidental overwrite.
4. Validity, supersession, contradiction and current-state signals help separate active state from history.
5. Snapshots, diffs and confirmed rollback provide a recovery path for unsafe agent runs.
6. The Python SDK, CLI and stdio MCP adapter let coding agents use the same state surface.

The local runtime remains separate from the public cloud-only PyPI package. See the [architecture guide](../architecture.md)
and [public artifact boundary](../adr/0001-public-artifact-and-internal-runtime-boundary.md).

## A minimal hosted flow

```bash
pip install -U bilinc==2.2.0
bilinc start
bilinc login --api-key bil_live_...
bilinc quicktest
```

For an MCP client, the public package exposes the `bilinc.cloud_mcp` stdio server. The API key belongs in the client
environment; never commit it to a configuration file or paste it into an issue.

## What the current evidence says

The strongest public-facing receipt is the frozen LongMemEval-s retrieval guardrail:

- 500 questions
- Hit@5: `98.0%`
- NDCG@5: `0.913`
- no LLM reranker
- no paid judge API

This is an isolated component result, not an end-to-end hosted SLA, not a universal agent-memory score, and not a
competitor ranking. The [manifest](../../benchmarks/evidence/2026-08-04/longmemeval-frozen-final/manifest.json) records
the dataset, runner, metric and scope boundaries.

The repository also stores AMB legacy-v3 and official LoCoMo retrieval-component manifests. Those lanes remain
separately labeled because their harnesses, retrieval scope, judge requirements and metrics are not interchangeable.
The [evidence contract](../../benchmarks/evidence/README.md) explains how manifests are validated.

Official ConvoMem results are not claimed here because its unchanged evaluator/provider requirements were not run under
the approved release protocol.

## Try it, inspect it, challenge it

- [Quickstart](https://bilinc.space/docs/quickstart)
- [MCP setup](https://bilinc.space/docs/mcp)
- [Architecture](../architecture.md)
- [Evidence-aware recall](../evidence-aware-recall.md)
- [Benchmark evidence](../../benchmarks/evidence/README.md)
- [GitHub Discussions](https://github.com/atakanelik34/Bilinc/discussions)

The useful contribution is not another inflated aggregate. It is a reproducible failure case, a neutral capability
test, or a production integration that makes agent state safer to inspect and recover.

## License and terminology

The repository is licensed under BUSL-1.1. Describe Bilinc as source-available unless your use of the license supports a
different claim. The public PyPI artifact is the cloud-only SDK/CLI/MCP surface.
