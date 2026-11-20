---
status: accepted
date: 2026-11-20
decision-makers: Christopher Lepenik
---

# Record decisions as MADR files in docs/decisions

## Context and Problem Statement

phonepad is meant to grow (see the ideas in `docs/STATE.md`). Later sessions, human or agent,
need to know why it is built the way it is without re-deriving it.

## Decision Outcome

Chosen option: one [MADR 4.0.0](https://adr.github.io/madr/) file per decision, indexed in
`README.md`, the same as in diary-desk. Requirements live in `docs/SPEC.md`, history in
`docs/worklog.md`.
