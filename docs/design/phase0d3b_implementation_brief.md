# Phase 0D3B implementation brief

This is a hand-off only; 0D3B is not entered here.

Implement the approved simulator section in the existing Jinja2 shell using a small vanilla JS/CSS module. Reuse `apiGet`/`storyosApiRequest`, project-context binding, abort generation, and the two read-only Review GET routes. Parse `mode`, `view`, `project`, `timeline_id`, `chapter_id`, and optional `panel_execution_id`; preserve them through 404. Render authoritative values from their own DOM region and model supplement in an explicitly labeled secondary region. Keep conflict unresolved and usage null as 未提供.

Before implementation, obtain product sign-off on the URL shape, fixture-to-real selection behavior, and whether the current shell should expose the mode switch in the topbar or sidebar. Do not add a package manager, bundler, write action, rerun action, or backend field.
