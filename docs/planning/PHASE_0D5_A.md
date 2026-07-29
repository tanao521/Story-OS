# Phase 0D5-A — Simulator Usable Loop Frontend Design

Status: **PASSED**  
Implementation: **NOT ENTERED**  
Next phases: **0D5-B/C/D/RC NOT AUTHORIZED**

## Deliverables

The design set defines the usable-loop information architecture, complete interaction state machine, default simulator entry and scope resolution, branch controls, multi-Turn continuation, Turn History, Candidate Review, durable approval decision, commit confirmation/recovery, Chapter Completion, URL/recovery contract, component contracts, responsive behavior, accessibility, Traditional Writing Mode isolation, and backend gap classification.

## Design decision

The simulator remains a high-density night editing workbench inside the existing App Shell. The authority spine is the only new signature: a quiet scope/stage rule that makes authority changes legible without turning the product into a dashboard or chat interface.

## Approval authority

Approval must be durable and fingerprint-bound. The current backend evidence does not expose a Narrative Chapter Candidate approval route; this is explicitly classified as `REQUIRED_BACKEND_GAP_FOR_0D5-B`. The frontend must not emulate approval in local state.

## Safety

Production code changes: 0; test changes: 0; Provider calls: 0; Canon writes: 0; Chroma writes: 0; Git write operations: 0; real project mutations: 0. 0D5-B is not entered.

