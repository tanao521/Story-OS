# Story OS Project Instructions

## Project identity

Story OS is a local AI novel-writing workstation for long-form fiction.

The core workflow is:

1. Create story spec
2. Generate high-level story blueprint
3. Generate characters and world bible
4. Build current context
5. Plan next chapter
6. Write draft
7. Edit draft
8. Manual edit
9. Quality check
10. Human review
11. Commit chapter
12. Sync Obsidian
13. Index vector memory

The project is designed for chapter-by-chapter rolling generation, not for generating a whole novel at once.

---

## Core architecture rules

- `main.py` only parses CLI commands and dispatches commands.
- `commands.py` owns command functions.
- `system/*.py` owns business logic.
- `web/routes.py` must call `commands.py` or `system/*.py`.
- Do not duplicate business logic inside Web routes.
- Web is only an operation and display layer.
- State must be stored in `data/state.json`.
- `commit-chapter` is the only normal operation that advances `current_chapter`.

---

## Writing workflow rules

- Do not generate multiple chapters in one action.
- Do not bypass the review gate.
- Do not auto-commit chapters by default.
- `plan-next` only plans the next chapter.
- `write-draft` only writes the current chapter draft.
- `edit-draft` only edits the current chapter draft.
- `manual` versions are human-edited versions.
- Manual versions must not overwrite draft or edited versions.
- Manual save must not advance `current_chapter`.
- Only review approval / commit-chapter may enter text into official chapters.

---

## First-run Web rule

If `data/story_spec.json` is missing, Web must show the first-run novel setup wizard.

The user must be able to create a novel project from zero in the Web UI before using chapter generation.

The setup wizard must collect:

- Novel title
- Genre
- Length type
- Target word count
- World style
- Tone
- Writing style
- Narration
- Character structure
- Romance level
- Focus tags
- Avoid list
- Anti-AI style rules
- Optional DeepSeek optimization

Do not make the user run CLI setup before using Web.

---

## Version rules

Supported version types:

- `draft`
- `edited`
- `manual`

Version priority for selection and commit:

1. selected version
2. latest manual
3. latest edited
4. latest draft

Manual versions are stored in:

```text
data/manual/
```

Manual version files use:

```text
chapter_001_manual_v001.json
chapter_001_manual_v001.md
```

---

## Memory rules

Story OS uses:

- Obsidian as human-readable long-term memory
- Chroma/vector index as machine-readable semantic memory
- summaries as compressed long-term chapter memory
- recent 3 chapters as working context

Do not put the full novel into the model context.

Older chapters should be represented by summaries and retrieval.

---

## Safety rules

- Do not expose API keys.
- Do not print `.env` content.
- Do not write API keys into config files.
- Do not show secrets in Web UI.
- Do not call external models during tests.
- Do not call DeepSeek during tests.
- Do not call local models during tests.
- Do not write to the real Obsidian vault during tests.
- Do not rebuild the real Chroma database during tests.

---

## Frontend rules

- Use native HTML, CSS, and JavaScript unless explicitly requested.
- Do not introduce React or Vue unless explicitly requested.
- Do not use external CDN.
- Do not load network fonts.
- Do not leave browser default white-background styling.
- Web UI should be a local dark writing workstation.
- Long text preview and editing areas must be readable and scrollable.
- Web must work at `http://127.0.0.1`.

---

## Testing rules

Always run:

```bash
pytest
```

Tests must be deterministic and must not rely on external services.

When adding Web APIs, use FastAPI TestClient.

When modifying CLI commands, keep Windows path compatibility.

All files must be UTF-8.

---

## Documentation rules

Update README when adding new commands, Web APIs, or workflow steps.

When completing an iteration, report:

1. Updated file tree
2. New or changed commands
3. New or changed APIs
4. Example output
5. pytest result
