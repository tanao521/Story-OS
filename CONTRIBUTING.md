# Contributing to Story OS

Thank you for helping improve Story OS. Contributions are welcome in source
code, tests, documentation, examples, accessibility, and architecture
feedback. The project is experimental, so focused changes with clear evidence
are especially useful.

## Before You Start

Please read the root [README](README.md) and [SECURITY.md](SECURITY.md).
Search existing issues before opening a new one. Do not include private novels,
API keys, local vault paths, vector indexes, generated project data, or other
personal runtime data in an issue or pull request.

## Local Development

The repository root is the installation and development entry point.
`story-os-demo/` is the historical directory containing the main implementation
source tree.

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python main.py self-check
```

On Windows, activate the environment with `.\.venv\Scripts\Activate.ps1`.
On macOS or Linux, use `source .venv/bin/activate`.

Installation is performed from the repository root. The test suite currently
assumes `story-os-demo` as its working directory because of the repository's
historical source layout:

```bash
cd story-os-demo
python -m pytest -q
```

Tests must be deterministic and offline. Do not use real model credentials,
call external model services, write to a real Obsidian vault, or rebuild a
production vector index during tests.

## Reporting Bugs

Open an issue with:

- a concise description and expected behavior;
- reproducible steps from a clean or documented local setup;
- Python version and operating system;
- the relevant command, route, or test name;
- a minimal sanitized example; and
- logs or tracebacks with secrets and private content removed.

Do not use a public issue for a security vulnerability. Follow
[SECURITY.md](SECURITY.md) instead.

## Feature Suggestions

Explain the user or contributor problem, the proposed behavior, the impact on
human review and data boundaries, and whether the idea is compatible with the
current workflow. Suggestions should not assume that Story OS is a general
multi-agent framework or a production service.

## Code and Documentation Contributions

Keep changes focused and preserve existing behavior unless the change is the
explicit subject of the contribution. Add or update focused tests when
practical. Update documentation when commands, APIs, configuration, or
workflow behavior changes. Avoid broad refactors, unrelated formatting, and
new dependencies without a clear justification.

For documentation changes, check command names, paths, platform notes, and
claims about model or integration support against the current implementation.

## Pull Requests

A pull request should:

1. describe the problem and the intended change;
2. identify affected areas and known limitations;
3. include tests or explain why tests are not practical;
4. include documentation updates when relevant; and
5. avoid unrelated generated files, local data, and temporary artifacts.

Before opening a pull request, run the smallest relevant checks and, when the
change is broad, the full configured test suite:

```bash
cd story-os-demo
python -m pytest -q
```

There is no promise of a fixed review timeline or automatic release process.
Maintainers may request narrower scope or additional evidence.

## AI-Assisted Contributions

AI tools may be used to explore, draft, test, or review changes. Contributors
remain responsible for understanding the submitted code, checking its license
compatibility, validating behavior, and providing appropriate tests. If a
large portion of a contribution was generated or substantially assisted by an
AI tool, briefly disclose that scope in the pull request. Do not submit code
that has not been reviewed and understood.

## License

By contributing intentionally to this repository, you agree that your
contribution is provided under the [Apache License 2.0](LICENSE), subject to
the terms in that license.
