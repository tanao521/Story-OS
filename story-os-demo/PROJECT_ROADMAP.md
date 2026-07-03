# Story OS Project Roadmap

## Completed versions

- v0.1: Novel project setup wizard
- v0.2: High-level story blueprint
- v0.3: Character cards + world bible
- v0.4: Next chapter plan generator
- v0.5: Current chapter draft generator
- v0.6: Chapter commit / state update / summary memory
- v0.7: Recent chapters + summary memory strategy
- v0.8: Sync to real Obsidian Vault
- v0.9: Local vector database / semantic retrieval
- v1.0: DeepSeek planning layer
- v1.1: Local model integration for `write-draft`
- v1.2: DeepSeek integration for `edit-draft`
- v1.3: One-command single chapter pipeline `run-chapter`
- v1.4: Human review gate `review-draft`
- v1.5: Draft version management / multi-version comparison
- v1.6: Quality checker
- v1.7: Project status dashboard
- v1.8: Todo system
- v1.9: Creative memory Q&A
- v2.0: Unified creative control shell
- v2.1: Lightweight Web console MVP
- v2.1.2: Web first-run novel setup wizard
- v2.2: Web text preview + version diff + quality report display
- v2.3: Web online manual editing + `manual` versions

---

## Current stable workflow

```text
setup / first-run wizard
  ->
blueprint
  ->
build-assets
  ->
build-context
  ->
plan-next
  ->
write-draft
  ->
edit-draft
  ->
manual edit
  ->
quality-check
  ->
review-draft
  ->
commit-chapter
  ->
sync-obsidian
  ->
index-vault
```

---

## Next planned versions

### v2.4: Memory Health

Goal:

Add a project consistency diagnostic system to check whether state, chapters, summaries, versions, selected version, quality reports, Obsidian sync, vector index, todos, and foreshadows are consistent.

Planned command:

```bash
python main.py memory-health
python main.py memory-health --json
python main.py memory-health --full
python main.py memory-health --fix
```

Planned Web tab:

```text
记忆健康
```

---

### v2.5: Stabilization

Goal:

Clean up bugs, improve README, stabilize commands, improve error messages, ensure Windows compatibility, and prepare the project as a usable local writing workstation.

---

## Hard constraints

- Do not generate full novel at once.
- Do not skip human review.
- Do not auto-commit chapters.
- Do not expose secrets.
- Do not duplicate business logic in Web routes.
- Do not call external services in tests.
