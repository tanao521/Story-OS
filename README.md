# Story OS

> An AI-native operating system for long-form creative production.

Story OS is a local-first, human-controlled workflow system for long-form
creative work. It explores how AI-assisted production can remain reviewable,
versioned, traceable, and useful across long-running projects. The current
implementation is centered on long-form fiction, with an experimental
simulator workflow in the local Web UI.

Story OS is not a one-click novel generator. AI output moves through explicit
workflow steps, version boundaries, human review gates, and long-term memory
before it becomes part of the formal project record.

## Why Story OS

Long-running creative work exposes limits that are easy to hide in short demos:

- model context is finite;
- continuity and project rules must survive many iterations;
- drafts, revisions, and approved content need different lifecycles;
- an AI suggestion should not silently become an authoritative change; and
- failures should be inspectable and recoverable.

Story OS treats these as workflow and state-management problems, not only as
prompting problems.

## Core Principles

- **Human in the loop** — important transitions and formal commits require an
  explicit human decision.
- **Long-term memory** — structured project data, summaries, local files, and
  optional vector retrieval support continuity across chapters.
- **Version-bound revisions** — draft, edited, and manual versions remain
  distinguishable and selectable.
- **Traceable state** — operations produce inspectable state, reports, and
  project artifacts.
- **Local-first boundaries** — project data is stored locally by default;
  external model services are optional configuration choices.
- **Graceful fallback** — core workflows can use local or mock behavior when a
  configured model service is unavailable.
- **Testable automation** — tests avoid real model calls, real Obsidian vaults,
  and real production vector indexes.

## Current Capabilities

The current codebase provides the following capabilities, with some advanced
areas still experimental:

- story project setup and high-level story blueprint generation;
- character, world, and writing-constraint assets;
- chapter-by-chapter planning and draft generation;
- revision, manual-edit, comparison, selection, and archival workflows;
- quality checks, review decisions, and controlled chapter commits;
- local summaries, context construction, memory health checks, and optional
  Chroma/vector indexing;
- optional Obsidian synchronization;
- Narrative Turn planning with preview and confirmation boundaries;
- branch and timeline workflows under active development;
- a local FastAPI Web UI and CLI; and
- automated tests covering core, API, Web, memory, version, review, recovery,
  and concurrency behavior.

Model providers and advanced integrations vary by configuration. The default
development and test workflows do not require a real API key or a live model
service.

## Architecture Overview

At a high level, Story OS separates creative state from model access and from
the presentation layer:

```text
Project data and state
        |
        v
Planning -> context and memory -> draft/revision versions
        |                                  |
        v                                  v
  review and evidence ----------------> commit authority
        |
        v
  local files, reports, optional Obsidian/vector integrations
```

- `core/` contains project and content workflow primitives.
- `system/` contains state, memory, version, review, commit, and integration
  services.
- `llm/` contains model-provider clients and fallback behavior.
- `web/` contains the FastAPI application, routes, templates, and static UI.
- `tests/` contains deterministic unit, API, integration, recovery, and
  concurrency checks.

## Repository Layout

The repository keeps a historical two-level layout. The repository root is the
installation and development entry point. `story-os-demo/` contains the main
implementation source tree; its name is retained for compatibility and is not
the public product name.

```text
.
├── pyproject.toml          # package, CLI, dependency, and pytest metadata
├── main.py                 # root compatibility launcher
├── README.md               # project home
├── story-os-demo/
│   ├── core/               # project and creative workflow code
│   ├── system/             # state, memory, versions, review, integrations
│   ├── llm/                # model-provider adapters
│   ├── web/                # FastAPI app and local UI
│   ├── tests/              # automated tests
│   └── .env.example        # optional local model configuration template
├── CONTRIBUTING.md
├── ROADMAP.md
├── SECURITY.md
└── LICENSE
```

## Quick Start

Requirements: Python 3.10 or newer.

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python main.py self-check
python main.py web
```

On macOS or Linux, activate the environment with:

```bash
source .venv/bin/activate
```

The Web UI is served at `http://127.0.0.1:7860` by default. The first run can
create a project through the Web setup flow. The basic CLI workflow is:

```bash
python main.py setup
python main.py blueprint
python main.py build-assets
python main.py plan-next
python main.py write-draft
python main.py review-draft
python main.py commit-chapter
```

The exact available commands can change as the project evolves. The root
launcher and `story-os-demo/main.py` contain the current command dispatch.

### Optional model configuration

Offline and fallback paths are available for development. To configure a
provider for local use, copy the template from the repository root with:

```powershell
Copy-Item story-os-demo\.env.example story-os-demo\.env
```

Then edit the local file without committing it. Provider availability,
credentials, network access, and model behavior are outside the repository's
control. Tests must remain offline and must not use real credentials.

## Development and Testing

Install development dependencies from the repository root:

```bash
python -m pip install -e ".[dev]"
```

Run the configured test suite:

```bash
cd story-os-demo
python -m pytest -q
```

The test suite currently assumes `story-os-demo` as its working directory
because of the repository's historical source layout.

Run a focused test file while iterating:

```bash
cd story-os-demo
python -m pytest tests/test_web_routes.py -q
```

Tests are designed to avoid external model calls, real API keys, real
Obsidian vault writes, and real production vector indexes. See
`CONTRIBUTING.md` for contribution expectations and validation guidance.

## Project Status

Story OS is an active open-source engineering project and remains
experimental. The core chapter workflow, local state model, versioned content
flow, review boundaries, Web UI, and automated test infrastructure are the
most established parts of the repository. Branch/timeline workflows and some
provider integrations are still under evaluation.

The project is not presented as production-ready infrastructure or as a
general-purpose multi-agent framework. Compatibility across all operating
systems, providers, and deployment modes is not yet guaranteed.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the public roadmap. Internal development
reports and historical planning material are intentionally not used as the
public roadmap.

## Contributing

Contributions are welcome in code, tests, documentation, examples, and
architecture feedback. Start with [CONTRIBUTING.md](CONTRIBUTING.md), and
review [SECURITY.md](SECURITY.md) before reporting a security issue.

## Security

Do not commit API keys, local novels, private character or world data, vector
indexes, or local runtime state. See [SECURITY.md](SECURITY.md) for reporting
guidance and project security boundaries.

## License

Story OS is released under the [Apache License 2.0](LICENSE).
