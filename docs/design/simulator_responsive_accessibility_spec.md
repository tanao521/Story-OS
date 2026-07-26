# Responsive and accessibility specification

Targets: 1440×900 desktop (three persona cards + audit rail), 1280×800 compact desktop (two persona columns and narrower rail), 768×1024 tablet (single primary flow with audit stack), and 390×844 mobile (single-column priority order).

At every width: status uses text + symbol + border, focus is a gold 2px `:focus-visible` outline, headings form a logical h1/h2 hierarchy, mode and fixture controls have labels, warnings use `aria-live="polite"`, and conflict carries literal `unresolved`. Touch targets are at least 40px. No core region requires horizontal scrolling.

`prefers-reduced-motion: reduce` disables transitions and animation. Persona cards preserve authoritative order; on narrow screens the audit stack follows conflict/evidence priority. Screen-reader users encounter status, authority, cards, conflicts, then audit summaries in that order.

Prototype verification is DOM/CSS-based; browser screenshot limitations are recorded in the delivery report if the local browser cannot load the fixture directory.

## RC2 responsive containment

At widths up to 900px the review grid becomes one column; the audit column follows the primary content as a vertical stack. Nested grid and flex children use `min-width: 0` so min-content values cannot paint into a neighboring card. At 760px and below, controls and agreement/conflict content stack naturally, and authority metrics use zero-minimum tracks. The panel-status metric presents human-readable labels (for example, `source_missing` is shown as `来源缺失`) while short missing values such as `未提供` remain unbroken.
