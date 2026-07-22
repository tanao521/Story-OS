# Responsive and accessibility specification

Targets: 1440×900 desktop (three persona cards + audit rail), 1280×800 compact desktop (two persona columns and narrower rail), 768×1024 tablet (single primary flow with audit stack), and 390×844 mobile (single-column priority order).

At every width: status uses text + symbol + border, focus is a gold 2px `:focus-visible` outline, headings form a logical h1/h2 hierarchy, mode and fixture controls have labels, warnings use `aria-live="polite"`, and conflict carries literal `unresolved`. Touch targets are at least 40px. No core region requires horizontal scrolling.

`prefers-reduced-motion: reduce` disables transitions and animation. Persona cards preserve authoritative order; on narrow screens the audit stack follows conflict/evidence priority. Screen-reader users encounter status, authority, cards, conflicts, then audit summaries in that order.

Prototype verification is DOM/CSS-based; browser screenshot limitations are recorded in the delivery report if the local browser cannot load the fixture directory.
