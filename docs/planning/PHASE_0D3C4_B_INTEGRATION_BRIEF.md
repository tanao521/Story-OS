# Phase 0D3C4-B Integration Brief

## OWNER DECISION REQUIRED

B0 completed a non-exact Strict policy design. It did not authorize B1,
register a counter, change a payload, enable Live, or approve a Canary.

The Owner must explicitly approve or reject:

1. Hybrid formula: `text + 512 + 64/message + ceil(text*25%) + 256 JSON`.
2. Strict ceilings: text 2,048; conservative input 3,584; output 512; total
   4,096; one Provider call per child; 60 seconds.
3. Explicit `thinking={"type":"disabled"}`.
4. JSON Output via `response_format={"type":"json_object"}` plus JSON prompt
   instruction/example, with empty content treated as failure and no retry.
5. Non-exact UI wording and `cost_estimate_available=false`.
6. Revision binding and old-Ticket invalidation.
7. Append-only, content-free usage reconciliation.
8. V3 asset restriction to Layer-A counts and fixtures only.
9. License risk: no bundling/redistribution/production dependency until a
   compliant provisioning route is separately approved.
10. CRITICAL/HIGH residual risks in the B0 risk matrix.
11. Future Canary gate: 12?20 independent fixtures, one call each, complete
    usage, no retry/fallback, and no reserve breach; maximum underestimation is
    decisive.

Owner choices:

- authorize a separately scoped **B1 implementation** of Strict only;
- continue **Strict Block**;
- wait for official V4 exactness/license evidence.

Until a choice is explicit:

- implementation is not authorized;
- conservative availability remains false;
- exact availability remains false;
- Production Live remains default-off;
- no Canary is permitted.
