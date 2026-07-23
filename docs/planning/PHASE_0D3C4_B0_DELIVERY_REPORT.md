# Phase 0D3C4-B0 Delivery Report

## Final status

- Phase 0D3C4-B0: **PASSED**
- Conservative Policy Design: **COMPLETE**
- Provider readiness: **NOT PASSED**
- Implementation: **NOT AUTHORIZED**
- Production Live: **DEFAULT-OFF**
- Owner decision: **REQUIRED**

## Required answers

- Reserve choice: **Hybrid**, because it retains a fixed framing floor and
  scales uncertainty with message count and Layer-A text size.
- Strict parameters: text 2,048; base 512; 64/message; uncertainty 25%; JSON
  256; thinking 0 only under explicit disable; conservative input 3,584;
  output 512; total 4,096; one call/child; timeout 60.
- Parameter basis: model id and API field semantics are official facts; all
  numeric limits/reserves are **Owner safety policy**, not DeepSeek facts.
- V3 Archive use: Layer-A text count and deterministic fixtures only.
- License: unresolved; no commit, bundle, redistribution, dependency, or
  production use. Future compliant provisioning needs separate approval.
- Thinking: explicitly disabled using `thinking={"type":"disabled"}`. Official
  docs support this; defaults must not be used.
- Structured Output: V4 supports `response_format={"type":"json_object"}`;
  prompt must mention JSON and provide format guidance; empty content is
  possible. The reviewed official sources do not establish combined
  thinking+JSON behavior or input-token overhead. Current Story OS sends
  neither the required response format from its execution path nor explicit
  thinking state.
- Count/send equality: a future implementation must count the same immutable
  canonical object the adapter sends, with no post-count additions.
- Reconciliation: safe local/estimate/Provider counts, delta/ratio, revisions,
  exact model id, timestamp, and fingerprint only; no content or secrets.
- Future Canary: proposed 12?20 independent fixtures, one call each, no retry
  or fallback, complete usage, all content classes covered. Maximum
  underestimation controls; any reserve breach fails.
- Public readiness: separate conservative mode/codes, exact=false, mandatory
  non-exact and cost-unavailable wording.
- UI: ??? Token ?? / ?? Provider ???? / ?? Live ??? /
  ????????.
- CRITICAL risks: V3/V4 drift, Chat overhead, thinking default, license,
  underestimation, policy drift, and Ticket reuse.
- HIGH risks include JSON overhead/empty content, model drift, missing usage,
  UI misunderstanding, archive distribution, unpredictable cost, and client
  limit tampering.
- Production code/dependencies: **none changed**.

## Offline simulation

The focused B0 test covers A0 Layer-A fixture counts for short Chinese,
English, mixed emoji, newlines, JSON, long Persona, a 2,048-token long excerpt,
one Persona, five independent children, explicit JSON/thinking reserves,
revision fingerprints, client clamping, unknown model, over-budget pre-call
blocking, and a socket canary.

Final command results and protected-data comparison are recorded after the
closing validation pass:

- B0 policy simulation focused: **7 passed**.
- B0 + 0D3C3 focused + 0D3C2-RC direct safety: **39 passed**.
- A0 Archive SHA-256 recheck: matched
  `c954ca6f6e54281d72d3c27e2430cea7663f81292b39982e2f97890c66c302de`.
- A0 fixed-JSON Layer-A reprobe: deterministic repeated ids; network attempts
  **0**. The Archive's own Python demo was not executed.
- `python -m compileall -q .`: **passed**.
- `pyproject.toml` and `uv.lock`: **unchanged by SHA-256 during B0**.
- Provider/API/credential/Token/cost: **0**.
- Chroma: **6/6 SHA-256 matches**.
- Authority/story assets: **16/16 SHA-256 matches**.
- Obsidian bindings: **30**.
- Real model/panel Runs: **0/0**.
- Real Live ticket/audit/ownership: **0/0/0**.
- Production capability: **absent/default-off**.

## Next step

Wait for Owner decision: authorize a separately scoped B1 Strict
implementation, continue Strict Block, or wait for official exactness/license
evidence. B0 does not choose on the Owner's behalf and does not enter Canary.
