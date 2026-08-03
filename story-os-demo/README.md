# Implementation Guide

This directory contains the main Story OS implementation. It is retained as a
historical source-directory name; the public project name is **Story OS**.

For the project overview, installation instructions, supported entry points,
and contribution workflow, start with the [repository root README](../README.md).
Installation and normal CLI or Web commands run from the repository root.
The test suite uses `story-os-demo` as its working directory because of the
historical source layout. This directory is not installed as a separate
project.

## Source Areas

- `core/` — project setup and creative workflow primitives.
- `system/` — state, memory, versions, review, commit, recovery, and external
  integration services.
- `llm/` — model-provider adapters, configuration, and fallback behavior.
- `web/` — FastAPI application, routes, templates, and static assets.
- `tests/` — deterministic tests for CLI, services, APIs, Web behavior, memory,
  versions, recovery, and concurrency.
- `schemas/` — data contracts used by workflow and integration code.
- `tools/` — development and inspection utilities.

## Local Development

From the repository root:

```bash
python -m pip install -e ".[dev]"
python main.py self-check
python main.py web
```

Run the complete test suite from `story-os-demo`:

```bash
cd story-os-demo
python -m pytest -q
```

The local configuration template is [`.env.example`](.env.example). Copy it
to `story-os-demo/.env` only when a provider or integration needs local
configuration. Never commit the resulting `.env` file or private project data.

## Implementation Boundaries

The Web layer is an operation and display layer; workflow state and business
rules belong in the core and system modules. The normal chapter lifecycle is
incremental: planning, drafting, revision, review, and commit are separate
steps. Tests must not call external models, write to a real Obsidian vault, or
rebuild a production vector index.
