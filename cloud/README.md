# Bilinc Cloud boundary

Sprint 1 keeps hosted-cloud primitives inside the existing Bilinc repository under a clearly bounded `cloud/`
surface.

## Why here first

- hosted memory runtime must reuse the Python Bilinc core rather than reimplementing it in TypeScript
- Cloud needs plan entitlements, API-key verification, and usage policy close to runtime authorization
- the code can still be split into a dedicated private repo later if commercial separation becomes necessary

## Current layout

- `src/bilinc/cloud/` — cloud-specific runtime primitives
- `tests/test_cloud_*.py` — isolated unit coverage for cloud rules
- `src/bilinc/cloud/runtime.py` — project-isolated runtime manager
- `src/bilinc/cloud/service.py` — internal FastAPI sidecar factory

## Schema ownership

The PostgreSQL control-plane schema is owned by `bilinc-site`, where the human-auth and organization/workspace
control plane lives:

- `/Users/busecimen/Downloads/Projeler/bilinc-site 2/db/migrations/0001_cloud_control_plane.sql`

The Python core runtime consumes project-scoped access decisions from `bilinc-site`; it does not own the
org/user/billing schema while the Cloud product is still split across repositories.

## Private-beta runtime layout

Hosted memory state is physically isolated per project:

```text
<BILINC_CLOUD_RUNTIME_DIR>/<project_id>/bilinc.db
<BILINC_CLOUD_RUNTIME_DIR>/<project_id>/snapshots/*.json
```

The internal sidecar exposes only project-scoped endpoints behind service-token auth:

- `POST /v1/projects/{project_id}/commit`
- `POST /v1/projects/{project_id}/recall`
- `GET /v1/projects/{project_id}/snapshots`
- `POST /v1/projects/{project_id}/snapshots`

The public Cloud API remains in `bilinc-site`, where API keys, entitlements, quotas, and usage events are
validated before any sidecar call is made.

## Boundary rule

Public-site UI and browser auth surfaces live in `bilinc-site`.
Hosted runtime and entitlement enforcement live with the Python Bilinc core.
Stripe is never part of hot-path runtime authorization.
