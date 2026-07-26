# Phase 0D3A2-RC1 Delivery Report

## Stage conclusion

**PASSED.** The browser closure gate for Phase 0D3A2 is complete. The isolated simulator review prototype was opened through a live local HTTP server, validated at all four required viewports, exercised across the required state fixtures, and checked for console/runtime and production-isolation regressions. No production code or API contract was changed.

## Root cause of `storyos-http`

`rg -n "storyos-http" .` returned exit 1 with no repository matches. The string is therefore from the external browser launcher/tool environment, not from Story OS. No custom protocol was registered, removed, or treated as an executable.

## Server and HTTP evidence

Final QA server: `py -m http.server 4174 --bind 127.0.0.1`, cwd `D:\novel\StoryOS`, listener `127.0.0.1:4174`, PID `33308`. Port 4173 had existing listeners (PIDs 48704 and 25904); the repo-root 4174 server was used because the prototype's `../../fixtures/...` URL must resolve from the repository root.

- Prototype HTML: HTTP 200.
- `ready-current.json`: HTTP 200.
- Browser URL: `http://127.0.0.1:4174/docs/design/prototypes/simulator-panel-review/`.
- No `file:///`, external CDN, external network resource, or real API request was used.

## Four-viewport browser QA

| Viewport / fixture | Browser result |
|---|---|
| 1440×900 / `ready-current` | `READY / 当前`; persona order 01/02/03; authority/model supplement separation visible |
| 1280×800 / `partial` | `PARTIAL / 部分完成`; missing-persona and partial-result warnings visible |
| 768×1024 / `stale-mixed` | `STALE / 陈旧`; stale/model-source mismatch warnings visible |
| 390×844 / `source-missing` | `SOURCE MISSING / 来源缺失`; mobile warning and status remain visible |

Every viewport remained free of core horizontal overflow. The live browser also checked `not-run`, `failed`, `explicit-run-404`, `usage-null`, `agreements-conflicts`, and `warnings-multiple`. The 404 state remained `FAILED` with `PANEL_RUN_NOT_FOUND` and retained safe project/timeline/chapter context; usage null rendered “未提供”; conflicts explicitly rendered `unresolved` and agreements/conflicts were not color-only.

## Console, accessibility, and isolation

- Browser console errors/warnings: **none in each of the four target viewports** (0 entries per viewport).
- No unhandled rejection, fixture 404, external-resource failure, real `/api/` request, absolute-path leak, secret/prompt/chapter text, or raw exception was observed.
- Keyboard focus remained visible/identifiable on the labelled fixture selector; reduced-motion CSS media query is present; status language is semantic/textual.

## Screenshots

All four files are real browser captures saved under the prototype directory:

```text
docs/design/prototypes/simulator-panel-review/screenshots/ready-1440x900.png
docs/design/prototypes/simulator-panel-review/screenshots/partial-1280x800.png
docs/design/prototypes/simulator-panel-review/screenshots/stale-768x1024.png
docs/design/prototypes/simulator-panel-review/screenshots/source-missing-390x844.png
```

## Regression and protection results

- Phase 0D2B3 + Web/route/static regression: **52 passed**.
- `python -m compileall -q .`: exit 0 (run from `story-os-demo`).
- `node --check .../prototype.js`: exit 0.
- 11 fixture JSON files parsed; sensitive canary clean.
- Production-reference and external-endpoint scans clean.
- `protected_ok=True`; Chroma 6, authority assets 16, Obsidian bindings 30; model/panel run JSON counts 0/0.

## Prototype fixes

None. The only access issue was environmental: port/root selection for the static server. It was resolved without modifying the three allowed prototype files. No backend, production template, API, provider, run lifecycle, Chroma, Obsidian, or story write path was touched.

## Product decisions

- **Mode-switch placement: APPROVED**
- **URL/context behavior: APPROVED**

## Change and hand-off audit

RC1 additions are the two planning reports and four screenshot artifacts. Existing dirty worktree changes were preserved and not included in this phase. No commit, push, reset, clean, rebase, or Phase 0D3B implementation was performed. The phase may hand off to the next product gate, subject to the existing 0D3B scope and safety constraints.
