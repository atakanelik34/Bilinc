# ADR 0001: Public Artifact and Internal Runtime Boundary

Status: accepted

## Context

Bilinc ships a hosted Cloud SDK, while its source repository also contains the
StatePlane runtime, local storage, evaluation, scheduler and local MCP internals.
The public package and source tree previously described those two surfaces as one
thing, leaving users and tests with contradictory expectations.

## Decision

The repository has two explicit contracts:

1. The public wheel and sdist contain only the Cloud SDK, public CLI and Cloud MCP
   adapter. `bilinc.CloudClient`, `bilinc.Bilinc`, `bilinc` CLI and
   `bilinc.cloud_mcp` are public artifact surfaces.
2. `bilinc.core`, storage, eval, integrations, local MCP, scheduler, observability,
   jobs and Cloud sidecar code are source-only internal runtime surfaces. They are
   deliberately excluded from public artifacts.

`atakanelik34/Bilinc` is the public canonical upstream. `ReARCLabs/Bilinc` is an
exact private mirror. New work merges to canonical first, then the exact resulting
commit is fast-forwarded to the mirror. Published historical tags are immutable.

## Consequences

- Public documentation cannot advertise `StatePlane`, local `--db` CLI commands or
  local MCP as wheel functionality.
- Internal docs and tests must visibly say `source-only/internal runtime`.
- CI has separate public-source, internal-runtime and built-artifact lanes.
- Scheduler remains source-only because the stdio and HTTP internal runtimes use it
  when `BILINC_ENABLE_SCHEDULER` is enabled.
- Benchmark results must identify whether they exercised product-core, a component,
  a calibrated adapter or a historical/invalid run.
