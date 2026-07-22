# Simulator wireframes

## Desktop (1440 × 900)

```text
┌ rail: brand / mode / nav ┐┌ topbar: chapter + context + Design Preview ┐
│                          │├ status banner ──────────────────────────────┤
│                          ││ AUTHORITATIVE PANEL                         │┌ audit rail ┐
│                          ││ score / risk / deterministic flags          ││ selection  │
│                          ││ PERSONA 01 │ PERSONA 02 │ PERSONA 03         ││ execution  │
│                          ││ AGREEMENT  │ CONFLICT (unresolved)           ││ evidence   │
└──────────────────────────┘└─────────────────────────────────────────────┘│ usage      │
                                                                             └────────────┘
```

## Narrow (390 × 844)

```text
┌ brand + mode switch ┐
├ chapter/context     ┤
├ status banner       ┤
├ authoritative       ┤
├ persona 01          ┤
├ persona 02          ┤
├ agreement           ┤
├ conflict            ┤
├ audit summaries     ┤
└ warnings            ┘
```

The audit rail becomes a priority-ordered stack. Core warnings and status remain visible; no horizontal scrolling is required.
