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

## Chapter Archive Rules

The user must be able to archive unwanted chapters from the Web UI.

Chapter archive is the default removal behavior. It must not permanently delete files unless a separate explicit destructive delete feature is implemented later.

Archived chapters must not appear in normal chapter lists, version lists, context building, or future generation context.

Archiving a chapter must update data/state.json safely.

If the archived chapter is current_chapter, the system must recalculate current_chapter safely or return a clear message requiring the user to choose the next active chapter.

Archived chapter files should be moved under:

data/archive/chapters/chapter_XXX/

Archive metadata should be written to:

data/archive/chapters/chapter_XXX/archive_meta.json

Do not write to the real Obsidian vault during tests.
Do not rebuild the real Chroma database during tests.
Do not permanently delete chapter files by default.

---

## Current implementation notes

As of the latest local iteration, Web has these lifecycle pieces:

- If `data/story_spec.json` is missing, Web shows the first-run setup wizard.
- After project creation, Web must not jump straight into chapter drafting as if all planning assets are final.
- Dashboard includes a project archive panel for previewing and manually editing foundational project assets before chapter work.
- The project archive panel reads and saves only this allowlist:
  - `data/story_spec.json`
  - `data/story_blueprint.json`
  - `data/characters.json`
  - `data/world_bible.json`
  - `data/world_rules.json`
  - `data/project.md`
- JSON project archive saves must validate JSON before overwriting existing files. Invalid JSON must return an error and leave the old file unchanged.
- Project archive editing must not generate prose, call models, advance chapters, bypass review, or touch secrets.
- Dashboard includes an AI writing constraints panel. It stores user rules in `data/story_spec.json` under `writing_constraints` and syncs `anti_ai_style_rules`.
- Writing constraints currently include chapter word count min/max, pacing, chapter structure, must-follow rules, must-avoid rules, and AI-style limits.
- Top navigation and left sidebar should link to real dashboard sections, especially project archive, writing constraints, versions, memory health, Todo, and Ask Story.

Current Web APIs added for this lifecycle:

- `GET /api/project-assets`
- `POST /api/project-assets/{asset_id}`
- `GET /api/writing-constraints`
- `POST /api/writing-constraints`

Current related tests:

- `tests/test_project_assets_api.py`
- `tests/test_writing_constraints_api.py`


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

## Local execution notes

- The user wants high quality with minimal token and command waste. Prefer small, targeted reads and tests over broad scans.
- Do not leave temporary patch scripts or cache directories in the repo. Clean temporary `.pycache_*` and `.pytest_tmp_*` directories after validation.
- On this Windows workspace, `apply_patch` may fail with sandbox errors and Python may fail writing default `__pycache__`.
- For Python validation, prefer setting `PYTHONPYCACHEPREFIX` to a temporary directory under `D:\novel\StoryOS`, run the targeted check, then delete that temporary directory.
- Avoid full `pytest` unless the user explicitly asks for it or the change is broad enough to justify it. For narrow Web/API changes, run the specific affected test file(s), plus `python -m py_compile` and `node --check web/static/app.js` when relevant.
- If a long-running Web server or shell process is started for verification, stop it before finishing.


---

## Testing rules

Run the smallest verification set that covers the change. Use full `pytest` only when explicitly requested or when the change affects broad shared behavior.

Tests must be deterministic and must not rely on external services.

When adding Web APIs, use FastAPI TestClient.

When modifying CLI commands, keep Windows path compatibility.

All files must be UTF-8.

---

## Three-tier memory architecture (v1.0)

Writing and editing must use a 3-tier context. Never send the entire novel to the model.

### Layer 1 — Global Memory (always present, ~1000 chars)
Always included in every prompt. Built from `story_spec` + `characters` + `world_bible` + `state`.

- Title, genre, tone, writing style, narration, world style
- Protagonist core desires (max 3)
- World core rules (max 5)
- Core appeal points (`focus`)
- Forbidden items (`must_avoid` / `avoid`)
- Anti-AI style rules

### Layer 2 — Recent Memory (per-chapter, capped)
- **1 previous chapter** — committed text from `data/chapters/`, **tail 4000–8000 chars** (ending connects to current chapter)
- **3 recent summaries** — from `data/summaries/chapter_XXX_summary.json`, truncated to 300 chars each

### Layer 3 — Retrieval Memory (on-demand)
- ChromaDB vector search (`system/vector_memory.py`) — semantic retrieval
- Keyword-based fallback in `context_builder.py`
- Used by Ask Story panel and `build-context` command

Relevant files: `system/context_builder.py`, `core/draft_writer.py` (`_working_context_summary`, `_compact_prev_chapter`), `core/draft_editor_refine.py`

---

## Updated chapter workflow

```
1. 故事大纲 → 2. 角色与世界观 → 3. 背景构建 → 4. 章节规划
→ 5. 草稿生成 → 6. 审核 → 7. AI润色 → 8. 提交章节
```

Key changes from original:
- `pipeline_runner.py` no longer auto-runs `edit-draft` before review
- `approve_review()` runs `edit_draft_command()` → `commit_chapter_command()` (no quality check in approve chain)
- After commit: auto-cleans Draft/Edited/Manual versions for the committed chapter via `_cleanup_chapter_versions()`
- After commit: auto-syncs Obsidian + updates vector index

### Chapter title flow
1. Plan generates `第X章` as placeholder
2. Draft prompt instructs LLM: "第一行必须是章节标题，格式：# 第X章 标题名（4-8汉字）"
3. `_extract_title_from_text()` extracts the real title from LLM output
4. If extraction fails, falls back to plan title

Relevant files: `web/routes.py` (`approve_review`, `_cleanup_chapter_versions`), `system/pipeline_runner.py`, `core/draft_writer.py` (`_extract_title_from_text`), `core/next_chapter_planner.py` (`_chapter_title`)

---

## Vector database module (v0.9)

`system/vector_memory.py` — ChromaDB persistent vector index.

### Key API
- `build_or_update_index(data_dir)` — indexes chapters, summaries, characters, world bible. Returns command-style result.
- `search_similar(query, data_dir, max_results)` — semantic search returning `[{type, chapter_id, score, snippet, ...}]`
- `is_available(data_dir)` — True when index is built
- `collection_stats(data_dir)` — metadata about current collection

### Embedding strategy
- Primary: n-gram character hashing (384-dim, zero network, works offline)
- Upgrade path: `SentenceTransformerEmbeddingFunction("paraphrase-multilingual-MiniLM-L12-v2")` when model is cached
- Collection name: `storyos_memory` (stored in `data/chroma/`)

### Integration
- `commands.py`: `index_vault_command()` calls `build_or_update_index()`
- `system/story_qa.py`: `search_vector_memory_if_available()` calls `search_similar()`
- `system/context_builder.py`: injects `vector_retrieved_memories` into working context
- `system/status_dashboard.py`: shows chapters/chunks count
- `system/memory_health.py`: `check_vector_index()` validates ChromaDB state

### Requirements
- `chromadb` in requirements.txt
- `sentence-transformers` optional (for better Chinese semantics)

---

## Quality-driven refinement

Clicking "刷新质量" → `POST /api/quality-check` → `quality_check_command()`:

1. Resolves target version (prefers Edited over Manual over Draft)
2. `build_quality_report()` — uses DeepSeek v4 Pro for LLM evaluation (via `_llm_quality_evaluate()`) or falls back to local rules
3. If flags/suggestions exist → `refine_draft_with_quality_report()` from `core/draft_editor_refine.py`
4. Refinement prompt includes full 3-tier context + previous chapter tail 4000 chars from committed file
5. Guardrails:
   - Text change ratio ≤ 30% (line-level diff, rejects full rewrites)
   - Word count ≥ 50% of original
   - No AI self-reference phrases
   - No JSON output
6. Re-runs quality check on refined version, saves as `edited_vXXX`

### Refinement instructions by severity
- **high severity**: may restructure locally, must keep chapter goal + outline position
- **medium/low severity**: smallest possible edit, preserve original structure
- Never adds new plot points, characters, or world rules

Relevant files: `core/draft_editor_refine.py`, `system/quality_checker.py` (`_llm_quality_evaluate`), `commands.py` (`quality_check_command`)

---

## Model configuration

| Task | Model | Config Key |
|---|---|---|
| Quality check / evaluation | DeepSeek v4 Pro | `DEEPSEEK_MODEL` |
| Draft writing | Qwen 3.7 Max | `WRITE_MODEL_NAME` / `WRITE_MODEL_BASE_URL` |
| Draft editing (AI润色) | Qwen 3.7 Max | `WRITE_MODEL_NAME` (via `generate_with_api_model`) |
| Quality refinement | Qwen 3.7 Max | same as editing (`load_api_model_settings()`) |

`.env` must set:
- `USE_DEEPSEEK_FOR_EDITING=true`
- `USE_DEEPSEEK_FOR_QUALITY_CHECK=true`
- `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL`
- `WRITE_MODEL_API_KEY`, `WRITE_MODEL_BASE_URL`, `WRITE_MODEL_NAME`

---

## Committed chapter panel

Right sidebar panel "Published" shows:
- Summary line: "已提交到第X章" or "已提交到第X章 · 缺失第Y章"
- Compact row per chapter: `#N 标题` — click to view full text in preview area
- Each row calls `loadVersionContent("committed", chapter_id)`
- Committed text shows in full (no snippet) in preview area

API: `GET /api/versions` returns `committed` array
Content: `GET /api/versions/content?source_type=committed&version=N`
Direct patch: `POST /api/manual/commit-patch` (overwrites committed file, no review)

Relevant files: `web/static/app.js` (`loadCommittedChapters`), `web/templates/index.html`, `web/routes.py` (`api_commit_patch`), `commands.py` (`_scan_committed_chapters`)

---

## New and modified files

```
core/draft_editor_refine.py   # NEW — quality refinement with 3-tier context
system/vector_memory.py        # NEW — ChromaDB module
system/memory_health.py        # rewritten — all Chinese, ChromaDB checks
web/static/style.css            # committed panel, preview toggle, compact rows
web/static/app.js               # 3-tier flow track, committed panel, quality flow
web/templates/index.html        # committed panel, flow track, preview toggle
web/routes.py                   # approve flow, commit-patch, cleanup, constraints fix
web/schemas.py                  # committed source_type support
commands.py                     # 3-tier context, quality refinement, index-vault, title extraction
config.py                       # ChromaDB settings
core/draft_writer.py            # title extraction, tail truncation, prompt title requirement
core/next_chapter_planner.py    # chapter title placeholder
core/draft_editor.py            # _strip_llm_wrapper, _text_change_ratio
system/context_builder.py       # 3-tier memory builder, global_memory
system/quality_checker.py       # _llm_quality_evaluate (DeepSeek-based)
system/pipeline_runner.py       # edit-draft moved after review
system/status_dashboard.py      # vector stats, memory status
llm/prompts.py                  # DO NOT EDIT — encoding corruption risk
requirements.txt                # chromadb, sentence-transformers
```

---

## Environment variables reference

```bash
# Required
LLM_PROVIDER=api
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
USE_DEEPSEEK_FOR_EDITING=true
USE_DEEPSEEK_FOR_QUALITY_CHECK=true
USE_DEEPSEEK_FOR_QA=true

# Writing (Qwen)
WRITE_MODEL_API_KEY=sk-xxx
WRITE_MODEL_BASE_URL=https://ws-xxx.maas.aliyuncs.com/compatible-mode/v1
WRITE_MODEL_NAME=QWEN3.7-Max

# Optional
CHROMA_DIR=data/chroma
VECTOR_EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
VECTOR_COLLECTION_NAME=storyos_memory
OBSIDIAN_VAULT_DIR=D:/your-vault-path
OBSIDIAN_PROJECT_DIR_NAME=StoryOS
LOG_LEVEL=INFO
LLM_DEBUG=false
```

## Documentation rules

Update README when adding new commands, Web APIs, or workflow steps.

When completing an iteration, report:

1. Updated file tree
2. New or changed commands
3. New or changed APIs
4. Example output
5. pytest result
