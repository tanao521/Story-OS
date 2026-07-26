# Phase 0D3C4-B1-FIX — Reconciliation Containment & Asset Hardening

## Outcome

**Phase 0D3C4-B1-FIX: PASSED**

**Phase 0D3C4-B1: SEALED**

**Production Live: DEFAULT-OFF**

**Real Profile Activation: BLOCKED BY EXTERNAL ASSET/COMPLIANCE GATE**

**Canary: NOT AUTHORIZED**

## Scope

This phase fixes only the B1 security-review findings. It does not provision a
real tokenizer, activate a Profile, call a Provider, create a real Run/Ticket,
enable Production Live, or enter B2.

### Reconciliation containment

Record IDs accept only `[A-Za-z0-9_-]+`. Empty, whitespace, dot segments,
slashes, backslashes, absolute paths, drive paths, control characters and
Unicode identifiers are rejected with safe domain codes. The store creates
and canonicalizes its root, rejects a symlink root, verifies the target remains
directly under that root, and preserves exclusive append-only creation.

### Reconciliation invariants

Token and delta fields use `type(value) is int`, so booleans are rejected.
Counts, revisions, model id, 64-character hexadecimal fingerprint,
completeness state, delta and ratio must be internally consistent. Invalid
input is rejected; it is never normalized into a persistable record.

### Asset integrity and TOCTOU

The provisioning seam remains disabled by default. It accepts one explicit
absolute `.json` path and expected SHA-256. The file is opened once, checked as
a regular non-empty file under a 64 MiB ceiling, read through that descriptor,
hashed, UTF-8 decoded, and parsed as a non-empty JSON object. The loader
receives the exact validated immutable bytes and parsed object, not a path it
could reopen. No discovery, download, remote code, or content logging exists.

### Evaluator fail-closed

Unserializable or malformed payloads, invalid message shapes, counter errors,
bool/float/negative counts, bool/float/raised client limits, invalid call
limits, provider/model mismatch, and missing explicit thinking/JSON fields
return `CONSERVATIVE_TOKEN_BUDGET_UNAVAILABLE` without propagating raw errors.
Valid canonical payload hashes and the original Owner formula are unchanged.

Stop after B1-FIX.
