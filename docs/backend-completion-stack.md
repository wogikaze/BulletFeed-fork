# Backend completion stack

This branch is the integration target for the BulletFeed backend completion stack.

The completion target is not source coverage or UI breadth. The backend must implement a replayable, evidence-preserving knowledge-state pipeline that turns source observations into user-specific meaningful deltas.

## Invariants

1. Observations are append-only facts about what a source returned; current state is derived.
2. Ingest is idempotent and replayable.
3. Event identity is independent from semantic novelty.
4. Claim/state history is retained; state updates do not overwrite history.
5. Revision semantics distinguish NEW_FACT, DETAIL, STATE_UPDATE, CORRECTION, and UNRESOLVED_CONTRADICTION.
6. Backend event knowledge and per-user knownness are separate.
7. Novelty, relation, and importance are separate signals.
8. Every displayed claim has a traceable Evidence -> Observation -> original source chain.
9. Source count is not independent evidence count.
10. Retry, restart, duplicate ingest, delayed observations, and out-of-order delivery must not corrupt semantic state.

## First vertical slice

Statuspage Incident is the first structured source. The first end-to-end path is:

`Statuspage payload -> Observation -> Event -> Claim/State -> Revision -> Delta -> Evidence -> Feed/EventDetail projection -> UserExposure`

Generic crawling, RSS expansion, ANN indexes, advanced ranking, notification work, and frontend expansion stay outside this stack until the vertical slice and its replay/evaluation gates are green.

## Merge policy

Small child PRs merge into `completion-pr`. The parent PR remains open against `main` until the completion gates are satisfied. Child PRs should be test-first and independently reviewable.
