# Phase 0D3C4-B1 — Strict Conservative Budget Infrastructure

## Outcome

**Phase 0D3C4-B1: PASSED**

**Strict Conservative Infrastructure: IMPLEMENTED**

**Real Profile Activation: BLOCKED BY EXTERNAL ASSET/COMPLIANCE GATE**

**Production Live: DEFAULT-OFF**

**Canary: NOT AUTHORIZED**

## B1-FIX sealing update

Phase 0D3C4-B1-FIX closes the security-review findings:

- reconciliation record IDs are allowlisted and resolved beneath a canonical,
  non-symlink root with exclusive append-only creation;
- reconciliation records enforce strict integer, identity, fingerprint,
  completeness, delta, and ratio invariants;
- external Layer-A files are opened once, size bounded, hashed and parsed as a
  non-empty JSON object, and the loader receives those same immutable bytes;
- malformed evaluator inputs fail closed with a deterministic content-free
  failure fingerprint;
- tokenizer/dependency tests now state and exercise their actual scan scope.

**Phase 0D3C4-B1: SEALED**

## Implemented boundary

B1 adds an offline, server-owned, non-exact budget path for the exact pairing
`deepseek` / `deepseek-v4-flash`. It does not alter the exact-counter path.
The default runtime has no provisioned Layer-A asset, so conservative
availability, Consent readiness, Live readiness, and Production Live remain
false.

The strict policy is:

```text
estimate = text + 512 + 64*message_count + ceil(text*0.25) + 256 + 0
text <= 2048
conservative input <= 3584
output <= 512
total <= 4096
calls = 1 per child
timeout = 60
retry = 0
fallback = none
cost estimate = unavailable
```

These figures are Story OS Owner policy, not Provider tokenizer facts.

## Safety properties

- Layer-A counter protocol is separate from the exact Provider counter.
- External assets require explicit enablement, absolute trusted file, audited
  SHA-256, regular non-symlink JSON structure, and an injected loader.
- No asset discovery, download, bundling, redistribution, remote code, or
  character fallback exists.
- Strict requests include explicit `thinking={"type":"disabled"}` and
  `response_format={"type":"json_object"}` before counting.
- `ProviderRequest` freezes one canonical JSON snapshot; counting and sending
  receive fresh copies of that same snapshot.
- Registry/Ticket/Audit bind safe profile, policy, counter, canonical envelope,
  source, and context revisions/fingerprints.
- Usage reconciliation is append-only and content-free.

Stop after B1. Do not enter B2 or Canary.
