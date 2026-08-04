# Frozen benchmark protocol — 2026-08-04

`freeze.json` is the source-of-truth protocol matrix for this goal. It keeps
the historical AMB v3 harness separate from the current Vectorize AMB harness,
and keeps retrieval-component results separate from end-to-end QA results.

The clean AMB adapter is frozen by its SHA-256 before product-core
optimization. Official fixtures and datasets are never edited. A result may
enter the committed evidence contract only after its command, environment,
raw-result checksum, metric validation, and protocol hash are captured.

The current Vectorize AMB, official LoCoMo QA path, and official ConvoMem path
require external generation or judge models. They remain blocked rather than
receiving a non-equivalent local substitute. Component lanes may proceed when
their metric and scope are explicitly labeled.
