# Simulator front-end architecture audit

## Facts

`web/app.py` creates `FastAPI`, mounts `StaticFiles(directory=.../web/static)`, includes `web.routes`, and uses Jinja2. `web/routes.py` returns `index.html` for `/`. The template has a global sidebar, topbar, dashboard sections, and script tags for `app.js` and feature modules. Navigation calls `navigateToSection()` and scrolls to DOM anchors; it is not a client router. `app.js` exposes `apiRequest`, `apiGet`, and `apiPost` around `fetch`, with `AbortController` and stale-project-response protection. State is module/global JavaScript variables and DOM; no Redux-like store or browser persistence was found.

## Inventory

| Concern | Confirmed implementation | Audit implication |
|---|---|---|
| Source/page | `web/templates/index.html` | Add a simulator section to the existing shell; do not duplicate shell |
| Static client | `web/static/app.js` plus feature JS/CSS files | Vanilla modules and DOM renderers are the compatible extension point |
| Route | FastAPI/Jinja2 `/` and JSON routes | A view can be deep-linked by query/hash without SPA migration |
| Build | No `package.json`, Vite/Webpack, `tsconfig`, or frontend build script | Do not introduce a build tool in this phase |
| Tests | pytest suites, route/static guards, focused 0D2B3 tests | Validate Python/API regressions; frontend check is not applicable |
| Styling | `style.css`, `design-system.css`, feature CSS | Reuse existing tokens and density; avoid a disconnected visual system |

## Shell and routing candidates

1. **Recommended — shell-level mode switch and section.** Add a future `工作模式` control beside the existing project context; select `traditional` or `simulator`, keep one `index.html` shell, and render a simulator workspace section. Encode `mode`, `project_root` (or project id), `timeline_id`, `chapter_id`, and optional `panel_execution_id` in the URL. Deep links remain `/` plus query values and call the existing GET route through `apiGet`.
2. **Compatible alternative — shared-template `/simulator` route.** Serve a simulator-specific template that includes the same shell partial/style contract and uses the same query context. This gives a clean route but duplicates template composition and requires explicit context hand-off.

The first option is recommended because it preserves the current anchor navigation, avoids shell duplication, and can later add other persona views. Neither option changes the Review API.

## Risks and constraints

- No existing timeline selector was found in the shell; timeline must remain an explicit URL/context field until a product decision adds a selector.
- Review is read-only. Do not expose rerun, repair, conflict resolution, prompt, chapter text, endpoint, secret, or raw exception controls.
- URL state must be validated and encoded; unknown explicit execution id maps to the existing 404 state.
- Use semantic regions, keyboard focus, non-color status labels, responsive two-column-to-one-column behavior, and reduced-motion-safe transitions.
