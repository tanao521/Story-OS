# Phase 0D6-C-B-RC12

## Outcome

**PARTIALLY PASSED — RC13 REQUIRED.**

The Narrative Turn and chapter-progression canonical identity boundaries are
closed. Formal UUID requests now resolve one registered project root, keep the
UUID in browser/API/DTO and operation authority, and use the existing slug only
inside legacy stores. Real Chromium exposed one independent stale-response
defect in sibling-branch delayed GET, so FV2 is not authorized.

## Identity Boundary

- Canonical product identity: ProjectManager UUID.
- Storage identity: registered project root and directory slug.
- Resolver: the unchanged RC11 `ProjectIdentityResolver`.
- UUID failure: fail closed; there is no slug fallback.
- Explicit legacy compatibility: a non-UUID low-level call is accepted only
  when it exactly equals the already-bound project root name. It never converts
  a failed UUID or guessed name into storage authority.

Narrative Turn binds context and persists Turn records with the storage scope,
while product DTOs and confirmation operation claim/phase records retain the
canonical UUID.

Chapter progression validates readiness and performs Turn storage with the
storage scope, while readiness responses and start claim/result/preview scopes
retain the canonical UUID. Operation ID and exactly-once semantics are
unchanged.

## RC7 Classification

The RC7 injected client fixture predated the mandatory RC10 embedding
contract. Its local client ignored embeddings and depended on optional
`chromadb` merely to make the injected manager return a collection. The
fixture now supplies an explicit test embedding seam. Assertions were not
weakened and vector production code was not changed.

## Chromium Matrix

Passed:

- formal UUID project load;
- Narrative Turn UUID context and plan;
- readiness and start UUID scope;
- normal start and successor rebind;
- Existing Turn plus Back/Forward;
- Traditional delayed GET and POST;
- cross-project delayed GET and POST;
- sibling-branch delayed POST;
- response-loss replay with identical UUID request and one durable effect.

Failed:

- sibling-branch delayed GET: after switching from `main` to `sibling`, the
  held `main` READY response rendered in the sibling context.

Not promoted to an RC12 acceptance claim:

- formal later-completion browser reactivation. The production
  Compiler/Review/Commit completion regression passed, but RC12 cannot be
  complete after the earlier independent browser failure.

## Boundaries

Frontend production code, vector production code, registry data, project
directories, sealed DTO schemas, operation identifiers, Compiler, Review, and
Commit authority were not changed.

## FV2 Gate

FV2 remains unauthorized. RC13 should fix only the sibling-branch readiness
response epoch/context invalidation and then rerun the full browser matrix,
including formal later-completion reactivation.

