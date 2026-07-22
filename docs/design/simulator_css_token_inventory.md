# Simulator CSS token inventory

Source evidence: `story-os-demo/web/static/design-system.css` (`:root` lines 2–37 and shell rules) plus `style.css` and feature CSS.

| Existing token | Meaning/use | Prototype decision |
|---|---|---|
| `--bg-base #080b10`, `--bg-sidebar #0a0e14`, `--bg-workspace #0c1118` | dark shell layers | reused as page/rail/workspace foundations |
| `--bg-elevated #111721`, `--bg-hover`, `--bg-active` | surfaces and active navigation | reused for review cards and mode state |
| `--text-primary`, `--text-secondary`, `--text-muted` | text hierarchy | reused directly in semantic equivalents |
| `--border-subtle`, `--border-strong` | hairlines and controls | reused as dense audit dividers |
| `--accent-primary #7c6cf2`, `--accent-hover`, `--accent-soft` | interaction accent | reserved for model supplement and active mode |
| `--story-gold #bca374`, `--story-gold-soft` | Story OS editorial accent | reserved for authoritative panel/evidence rail |
| `--status-success`, `--status-warning`, `--status-error`, `--status-info` | state semantics | reused with text/icon labels, never color alone |
| `--font-body`, `--font-editorial`, `--font-mono` | body/editorial/data roles | reused for prose headings, UI, ids/metrics |
| `--radius-sm/md/lg`, transitions, shell widths | geometry/motion | prototype uses existing 8px family and reduced-motion override |

Missing but recommended semantic additions for production: `--review-authority`, `--review-supplement`, `--review-conflict`, `--review-stale`, and `--review-surface-quiet`, each aliasing existing palette values. Do not rewrite the global system in 0D3A2.

Existing risk: the broad dashboard surface and many feature styles can flatten hierarchy at high density. The prototype counters this with a gold authority rule, violet supplement inset, ruled audit column, and explicit section kickers rather than global CSS changes. Existing focus rules are retained; the prototype adds a visible `:focus-visible` outline.
