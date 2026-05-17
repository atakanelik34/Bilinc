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

## Schema ownership

The PostgreSQL control-plane schema is owned by `bilinc-site`, where the human-auth and organization/workspace
control plane lives:

- `/Users/busecimen/Downloads/Projeler/bilinc-site 2/db/migrations/0001_cloud_control_plane.sql`

The Python core runtime consumes project-scoped access decisions later; it does not own the org/user/billing
schema while the Cloud product is still split across repositories.

## Boundary rule

Public-site UI and browser auth surfaces live in `bilinc-site`.
Hosted runtime and entitlement enforcement live with the Python Bilinc core.
Stripe is never part of hot-path runtime authorization.
