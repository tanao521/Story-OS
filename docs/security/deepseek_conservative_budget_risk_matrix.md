# DeepSeek Conservative Budget Risk Matrix

All residual risks below require Owner acceptance before implementation.

| Risk | Existing control | Residual risk | Required mitigation | Severity |
| --- | --- | --- | --- | --- |
| V3/V4 tokenizer drift | V3 scope label | Layer-A count may differ | Keep non-exact; Canary maximum-underestimate gate | CRITICAL |
| Chat overhead low estimate | Fixed/per-message reserve | Hosted framing unknown | Same counted/sent payload; fail on reserve breach | CRITICAL |
| JSON hidden overhead | 256 reserve | Provider overhead undocumented | Explicit JSON payload; reconcile usage | HIGH |
| Thinking tokens | Proposed explicit disable | Missing field currently defaults enabled | Send and fingerprint `thinking=disabled` | CRITICAL |
| Alias/model drift | Exact model id | Unversioned hosted behavior can change | Pin model id and policy revision; invalidate Tickets | HIGH |
| License unidentified | Archive not in repo | Production use/distribution unauthorized | Obtain terms or compliant external provisioning | CRITICAL |
| Archive redistribution | Documentation-only evidence | Accidental bundling | Hash/provenance check and packaging exclusion | HIGH |
| Missing Provider usage | Reconciliation required | No comparison possible | Mark reconciliation incomplete; no tier promotion | HIGH |
| Underestimation | Strict ceiling/reserves | Request may exceed estimate | Pre-call block and maximum-underestimate Canary gate | CRITICAL |
| Excessive blocking | Low text/output ceiling | Valid requests rejected | Accept for Strict; never silently loosen | MEDIUM |
| User assumes exactness | Separate mode/codes | UI wording can mislead | Mandatory ????? and no cost estimate | HIGH |
| Policy revision drift | Revision in fingerprint | Old consent could carry old limits | Bind Registry/Ticket/Audit/Run; reject mismatch | CRITICAL |
| Ticket reuse | Existing consent/idempotency | Replay under changed policy | Expire/invalidate on any revision change | CRITICAL |
| Cost unpredictable | Cost estimate unavailable | Owner cannot pre-price request | Show unavailable; hard calls/output limits | HIGH |
| Client raises limits | Server-owned policy | Tampered request | Clamp to minimum; reject invalid values | HIGH |
| Empty JSON content | Official warning | One permitted call may yield unusable output | No repair/retry; safe failed result | HIGH |

Risk acceptance does not make the counter exact or enable Production Live.
