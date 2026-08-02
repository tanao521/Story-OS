# Security Policy

Story OS is a local-first application that can be configured to use external
model providers and optional local integrations. Treat project content and
configuration as sensitive unless you have explicitly decided otherwise.

## Do Not Commit Sensitive Data

Never commit:

- API keys, access tokens, model credentials, or `.env` files;
- private novels, character profiles, world-building material, or user prompts;
- local vector databases, Obsidian vault contents, or generated project data;
- local machine paths that reveal private workspaces; or
- logs containing prompts, responses, credentials, or private content.

Use `story-os-demo/.env.example` as a configuration template. Keep real values
in an ignored local file and rotate a credential immediately if it is exposed.

## Security Boundaries

Contributors should consider:

- path traversal and workspace escape through project or integration paths;
- symbolic links that point outside the intended workspace;
- untrusted project data reaching file, Web, or model-provider operations;
- accidental disclosure through logs, error responses, reports, or Web UI; and
- writes to a real Obsidian vault or production vector index during tests.

Changes involving file paths, subprocesses, model requests, authentication,
serialization, or external integrations should include focused tests and a
clear explanation of the security boundary.

## Reporting a Vulnerability

Do not disclose exploitable details in a public issue, pull request, or forum.
If private vulnerability reporting is enabled for the repository, use the
repository’s GitHub **Security** tab. If that private channel is unavailable,
open a minimal public issue asking the maintainers for a private contact path;
do not include reproduction details, secrets, or exploit code in that issue.

Please include, through a private channel when possible:

- the affected version or commit;
- a concise description of the impact;
- minimal reproduction steps with sanitized data;
- the affected file, route, command, or configuration; and
- any suggested mitigation.

This project does not currently promise a fixed response time or claim a
dedicated security response team. We will assess reports based on their
reproducibility and impact.
