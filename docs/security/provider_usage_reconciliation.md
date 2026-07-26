# Provider Usage Reconciliation

`ProviderUsageReconciliation` is an append-only, content-free observation
record. It stores only:

- local Layer-A text tokens;
- conservative input estimate;
- optional Provider prompt tokens;
- delta and ratio;
- policy/profile/counter revisions;
- exact model id;
- safe request fingerprint;
- completeness and timestamp.

It never stores prompt, chapter text, schema, credential, endpoint, local path,
raw response, or raw exception. Missing Provider usage is recorded as
`incomplete`; it is not inferred.

Reconciliation never mutates policy, reserves, Profile readiness, retry, or
fallback. B1 tests use fake usage only. Real reconciliation records remain
zero.

## B1-FIX containment

Record IDs are restricted to ASCII letters, digits, `_` and `-`. The canonical
root must not be a symlink, the resolved target must remain directly inside
that root, and creation is exclusive. Safe domain errors do not expose paths.

Frozen records strictly reject booleans as integers, negative counts, blank
revisions/model ids, malformed fingerprints, unsupported completeness values,
and inconsistent Provider count/delta/ratio combinations.
