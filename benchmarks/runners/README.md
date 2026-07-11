# Canonical Benchmark Runners

Place a reproducible runner here only when it executes a documented benchmark
from a clean commit and emits an evidence manifest. Runners must use the shared
metric helpers in `benchmarks.metrics`; a result from this directory is not a
product claim until its evidence manifest is reproducible.

The legacy scripts in the benchmark root are retained as historical inputs while
they are migrated or replaced. Do not add new benchmark-specific aliases, caches
or normalization to a runner in this directory.
