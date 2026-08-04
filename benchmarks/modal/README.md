# Modal benchmark runner

`amb_runner.py` is an ephemeral, single-use Modal runner for the frozen
historical AMB v3 protocol. It uses the exact npm package version and exact
MCP adapter contract recorded in the protocol freeze. The App is tagged with
the goal and benchmark identifiers, and no Modal Volume or secret is used.

Before a full remote run, verify the remaining budget and current protocol
hash locally. Capture the returned receipt and raw result under the ignored
`benchmarks/runs/` area, then query billing by the same goal tags. The runner
must not be changed after the corresponding baseline or candidate protocol is
frozen.
