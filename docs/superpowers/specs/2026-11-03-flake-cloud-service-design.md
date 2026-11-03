# FLAKE-CLOUD-SERVICE: `tests/test_cloud_service.py` fails intermittently with a SQLite thread error

## Symptom
On plain origin/main (5578d27) `tests/test_cloud_service.py` sometimes fails with
`sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread` at `core/audit.py:195`
(`self.conn.execute("BEGIN IMMEDIATE")` inside `AuditTrail.log`). It was first seen on 2 of 4 runs of the file; the failing test varied.

## Reproduction (measured here, not assumed)
- 6 runs of the file on plain origin/main in a worktree: 6 passes. 8 runs in the main checkout: 8 passes. 12 more runs: 12 passes.
- Under load, 3 rounds of 8 parallel runs of the same file (24 runs): 3 runs failed with exactly that error (the failing run printed
  two `ProgrammingError` lines each); the rest passed. So it is timing dependent and appears when the machine is busy, which
  is why it looked random.

## Root cause
1. The hosted runtime creates a project's plane lazily on the first request, including its SQLite `AuditTrail`, whose connection
   is opened with the default `check_same_thread=True` (`core/audit.py:136`). The SQLite storage backend opens with
   `check_same_thread=False` (storage/sqlite.py:93); the audit trail does not, although its docstring says it is thread-safe (it
   has a `threading.Lock`).
2. Every test in `test_cloud_service.py` builds `TestClient(create_app(...))` WITHOUT `with`. Starlette's TestClient then
   starts a new anyio portal, which means a new thread with its own event loop, for every request. The plane created while serving
   request 1 lives in the manager, and request 2 uses its audit connection from a different thread.
3. Python reuses thread identifiers after a thread exits, so the SQLite check usually passes by luck (request 2's thread gets
   request 1's identifier) and fails when the identifiers differ, which happens under load.
4. All other test files that use `TestClient` (`test_cloud_memory_review.py`, `test_mcp_http.py`, `test_purge.py`,
   `test_secret_scan.py`) use `with TestClient(...)`, which keeps one portal thread for the whole test; only this file does not.

It is not a production bug found by this investigation: the hosted sidecar runs on one event loop thread and nothing in the
runtime calls the SQLite audit trail from a worker thread. The audit trail's thread binding is a latent limit (it would break
any future caller that moves audit writes into `asyncio.to_thread`), not something triggered today.

## Approaches
1. Product: open the audit connection with `check_same_thread=False`. Removes the error and the latent limit, but the audit
   trail's read paths (`verify_integrity`, `get_history`, `has_purgeable_rows`, ...) use the connection outside its lock, so allowing
   cross-thread use means also locking those paths. A change to audit internals to fix a test harness problem.
2. Test: use the client the way the other files do, as a context manager, so every request of a test runs on one thread.
   One small fixture, no product change.
3. Skip or retry the flaky tests. Hides the failure; rejected.

Chosen: 2, plus a characterization test that records the audit trail's thread binding as a known limit, so the limit is
documented and a later change to it (approach 1) is a conscious one.

## Changes
- `tests/test_cloud_service.py`: a `client` fixture that yields `with TestClient(create_app(runtime_dir=tmp_path,
  sidecar_token="secret")) as client`; the ten tests use it instead of building a client per test. A test pins the observable behaviour: a handler records `asyncio.get_running_loop()` across three requests of the fixture's client and the loops must be the same object (the loops are
  kept in a list so none is garbage collected and its address reused, which is also why thread identifiers are not used; no private Starlette attribute), so a future edit back to a bare `TestClient` is caught.
- `tests/test_audit_thread_binding.py`: an `AuditTrail` created on one thread raises `sqlite3.ProgrammingError` when `log` is
  called from another thread while the first thread is alive (deterministic, no timing); with a docstring that names it plainly: "known limit, not a contract"; a failure here is expected once approach 1 is done and the test
  is then updated on purpose. The first thread is kept alive with an `Event` (no sleeps).
- A second, characterization test shows the opposite for a bare `TestClient` (a new loop per request). It describes Starlette's current
  behaviour, not Bilinc's: if a future Starlette reuses the portal it fails and can simply be removed; the fixture guard above is the one that protects the suite.
- No change under `src/`.
- Side effect, to be stated in the ready note: entering the client runs the app's lifespan, so `manager.close()` (cloud/service.py:213-216) now
  runs at the end of each test. I check that no test in the file relies on state surviving across two app instances in one `tmp_path`.

## Test plan
- Red first (measured): the stress runs above (3 of 24 fail on the unchanged file). After the change the same stress, 3 rounds of 8
  parallel runs, must give 24 passes; the result is recorded in the ready note with the exact commands, and I make no claim beyond
  that sample.
- The deterministic audit-thread test and the one-portal test fail when the thing they pin is changed (hand mutation checks,
  recorded in the ready note, not committed).
- Full `bilinc-test` set and ruff as regression; the ready note records that the Postgres-marked tests ran (DSN set) and were not skipped.

## Release-chain impact
- None: tests only. No PyPI, SDK, hosted runtime, site, MCP registry, migration or CHANGELOG change.
