# BulletFeed 90/100 Completion Backlog

This document is the issue backlog for moving BulletFeed from the current strong replayable-backend baseline to a **>= 90/100 completion target**.

GitHub Issues is currently disabled for this repository, so each section below is written as an issue-ready specification. When Issues is enabled, create one issue per section and keep this file as the canonical checklist until all issues are closed by merged PRs.

## Scoring target

The backlog is complete when all child items are closed and the final head satisfies these floors:

- Acquisition / source operations: >= 90
- Observation / replay / projection integrity: >= 95
- Event identity / coreference: >= 85
- Semantic Delta correctness: >= 85
- Evidence / provenance / authority: >= 90
- Relation / Importance / Knownness: >= 80
- Android/API end-to-end behavior: >= 90
- Evaluation / CI / security / release readiness: >= 95
- Weighted product completion score: **>= 90/100**

The backlog intentionally does **not** prioritize generic crawler breadth, major UI redesign, ANN/KG infrastructure for its own sake, or additional source families before semantic correctness is strong.

---

# EPIC — [90/100] BulletFeed completion program

## Goal
Make BulletFeed reliably answer four questions end to end:

1. What was observed?
2. Which real-world Event/Claim does it belong to?
3. What meaningfully changed relative to prior state?
4. Is that change new, relevant, and important for this user?

## Exit criteria

- All P0/P1/P2 issues below are closed by merged PRs.
- The final commit has no unverified code changes after the last successful quality/security runs.
- Expanded blind Gold passes all release thresholds.
- Replay from the same Observation history reconstructs the same Event/State/Delta/User-visible state.
- No displayed claim lacks provenance.
- No known cross-user contamination or private-event access leak exists.

---

# P0 — Semantic correctness and release validity

## P0-01 — Reconcile `main` into `completion-pr` and require current-head gates

### Goal
Eliminate branch divergence and make CI evidence refer to the exact code being released.

### Acceptance criteria
- `completion-pr` contains the current `main` history without dropping completion work.
- Backend quality, backend security, dependency lock, and Android quality run on the resulting exact head.
- A guard fails release documentation if the recorded verified SHA differs from the current PR head.
- Full backend pytest, Ruff, dependency metadata/hash validation, Bandit/Semgrep/pip-audit, Android lint/format all pass.
- Any future commit invalidates the previous release verification until gates rerun.

### Close when
One PR reconciles the branch and adds/updates the exact-head release verification mechanism.

---

## P0-02 — Add semantic Claim canonicalization v1

### Goal
Normalize semantically equivalent Claim values/details before novelty classification without destroying raw Observation text.

### Scope
- Numeric formatting: `1000`, `1,000`, `one thousand` where unambiguous.
- Common unit/date/time normalization.
- Whitespace/case/punctuation normalization where meaning-preserving.
- Stable entity aliases supplied by structured source metadata.
- Preserve raw text and evidence separately from canonical representation.

### Acceptance criteria
- Canonical form is deterministic and replayable.
- Raw evidence remains unchanged and traceable.
- Normalization never rewrites negation, comparator direction, version identifiers, CVE/GHSA IDs, or source-specific stable IDs.
- Gold tests include positive and negative normalization pairs.

### Close when
Canonical Claim representation is persisted or deterministically derivable and used by semantic comparison.

---

## P0-03 — Implement semantic equivalence comparator v1

### Goal
Decide whether two Claim snapshots express the same fact even when text differs.

### Required cases
- Paraphrase / reordered clauses.
- Exact same fact with different formatting.
- Partial-detail extension versus equivalent restatement.
- Negation changes.
- Numeric/version/date changes.
- Entity alias equivalence.

### Acceptance criteria
- Returns at least `equivalent`, `not_equivalent`, `uncertain` with reason/confidence.
- Deterministic fallback exists when semantic model/service is unavailable.
- No external-model output can directly overwrite ledger truth without a typed decision boundary.
- Blind Gold equivalence precision/recall are separately reported.
- Uncertain cases are not silently treated as equivalent.

### Close when
Comparator is integrated below Delta classification with adversarial tests.

---

## P0-04 — Replace rule-only Semantic Delta with revision judge v1

### Goal
Upgrade `NEW_FACT / DETAIL / STATE_UPDATE / CORRECTION / UNRESOLVED_CONTRADICTION / NON_NOVEL` classification beyond raw value/detail equality.

### Acceptance criteria
- Uses canonicalized claims and semantic equivalence results.
- Correctly distinguishes equivalent restatement from DETAIL.
- Detects value changes hidden by similar prose.
- Maintains explicit source correction/conflict hints as high-authority signals.
- Preserves valid-time semantics for out-of-order replay.
- Returns reason/confidence for every classification.
- Expanded blind Gold revision macro-F1 >= 0.90 and existing release thresholds remain satisfied.

### Close when
Production ledger relation rebuild uses revision judge v1 and all replay tests still converge.

---

## P0-05 — Add Event candidate retrieval before coreference

### Goal
Avoid comparing every Observation to every Event while still retrieving plausible same-event candidates.

### Candidate signals
- Structured IDs / aliases.
- Publisher/source scope.
- Entity/product/package/repository identifiers.
- Time window.
- Normalized subject/title tokens.
- Existing canonical aliases.

### Acceptance criteria
- Candidate retrieval is deterministic for structured signals.
- Known hard positives are retrieved with >= 0.99 recall on Gold.
- Candidate cap prevents unbounded comparisons.
- Private-tenant candidate retrieval cannot leak cross-user private Event metadata.
- Metrics expose candidate recall and candidate set size.

### Close when
Generic coreference consumes candidate sets rather than adapter-specific direct matching only.

---

## P0-06 — Implement Event coreference decision engine v1

### Goal
Decide whether a candidate Observation/Claim belongs to an existing real-world Event or starts a new Event.

### Acceptance criteria
- Structured identity remains the strongest signal.
- Generic decision combines entity identity, topic, time, source, state/lifecycle, and semantic subject evidence.
- Explicit hard-negative behavior prefers false split over false merge when confidence is insufficient.
- Decision returns `same_event`, `different_event`, or `uncertain` with reason/confidence.
- Gold false merges = 0 and false split rate <= agreed threshold on expanded blind set.
- Source-specific special cases become evidence/features, not the only architecture.

### Close when
At least Statuspage-like, release/version, security/CVE, and policy/deprecation families pass one common coreference interface.

---

## P0-07 — Add reversible Event identity repair operations

### Goal
Make wrong event identity decisions repairable without deleting immutable Observation history.

### Required operations
- Alias one source event identity to canonical Event.
- Merge Events into canonical Event.
- Split Claims/Observations out of an incorrect Event.
- Rebuild relations, deltas, timeline, sources, feed projections, knownness mappings after repair.

### Acceptance criteria
- Repair operations are append/audit recorded.
- Replay after repair converges to the repaired identity.
- No orphan Delta/Evidence/FeedItem remains.
- Cross-user access grants are recalculated safely for private Events.
- Tests cover false merge repair and false split repair.

### Close when
Identity errors no longer require destructive DB surgery.

---

## P0-08 — Expand Gold v0.2 to >= 40 bundles / >= 250 observations

### Goal
Make the evaluation set large enough to challenge semantic and identity logic rather than certify fixtures written for the implementation.

### Required coverage
- Paraphrase/equivalent restatement.
- Same entity, different Event.
- Same Event, multiple Claims.
- Numeric/version/date changes.
- Negation and correction.
- Partial detail additions.
- Delayed/out-of-order updates.
- Multi-source dependence.
- Conflict and later resolution.
- Policy/deprecation/migration lifecycle.
- Security affected/fixed/duplicate advisory cases.

### Acceptance criteria
- >= 40 fixed bundles and >= 250 observations.
- At least half from real public-source observations or minimally normalized real snapshots.
- Every bundle declares provenance and whether it is pilot/dev/blind.
- Hard negatives are explicit.
- No generated case is counted as real-source evidence.

### Close when
Manifest and test harness enforce the coverage/count requirements.

---

## P0-09 — Enforce blind-evaluation isolation and leakage guards

### Goal
Prevent tuning production rules directly against all Gold answers.

### Acceptance criteria
- Pilot/dev and blind fixtures are stored or loaded through distinct paths.
- Routine development tests may expose pilot expected labels.
- Blind evaluation produces aggregate metrics without requiring production code to import label data.
- A CI check prevents source code from referencing blind fixture labels/IDs except evaluator/test harness allowlist.
- Release report records pilot and blind metrics separately.

### Close when
Blind metrics are trustworthy enough to guide a 90/100 completion claim.

---

## P0-10 — Add confidence calibration and abstention policy

### Goal
Represent uncertainty instead of forcing low-confidence semantic/coreference decisions.

### Acceptance criteria
- Equivalence, revision, and coreference decisions expose confidence.
- Low-confidence coreference defaults to new Event / unresolved linkage rather than false merge.
- Low-confidence truth conflicts do not overwrite current settled state.
- Calibration is evaluated on blind Gold using reliability buckets or equivalent metric.
- Thresholds are configuration/versioned and captured in replay metadata.

### Close when
The pipeline has a typed, testable abstention path for ambiguous cases.

---

# P1 — Continuous acquisition, evidence reasoning, personalization

## P1-01 — Put all production source families on persistent sync orchestration

### Goal
Move from callable pipelines to an actually continuous product.

### Required source families
- GitHub Release.
- Dependency security/SBOM/OSV.
- GitHub Advisory.
- Statuspage.
- RSS/Atom.
- JSON Feed.

### Acceptance criteria
- One persistent scheduling abstraction supports all families.
- Per-source cadence is configurable.
- Retry/backoff/lease semantics are shared where appropriate.
- Restart does not duplicate meaningful state.
- Removing a watched source/repository disables future sync safely.
- One-shot CLI mode remains available for deterministic tests/operations.

### Close when
No production source exists only as a manually callable crawl function.

---

## P1-02 — Add source freshness and ingestion-health state

### Goal
Know when BulletFeed is stale or a source pipeline is failing.

### Acceptance criteria
- Persist per-source last attempt, last success, last new Observation, failure count, and next scheduled run.
- Expose internal health metrics/log events for stale source detection.
- Distinguish `source had no changes` from `source could not be fetched`.
- Alerts/tests cover repeatedly failing and long-stale sources.
- Private source health does not leak source identity across users.

### Close when
Operators can answer “are we current?” without inspecting raw logs.

---

## P1-03 — Implement Claim authority resolver v1

### Goal
Make source authority explicit per Claim type rather than relying on source count.

### Examples
- Statuspage is authoritative for its incident state.
- Upstream GitHub advisory can outrank republished advisory metadata.
- OSV is useful aggregation but may depend on upstream advisory data.
- Vendor release/changelog outranks a discovery index for vendor lifecycle facts.

### Acceptance criteria
- Authority policy is typed and versioned.
- Resolution uses Claim slot/source family/context, not one global source ranking.
- Authority affects conflict resolution but never deletes contradictory Evidence.
- Tests cover authoritative correction, dependent source agreement, and competing authoritative sources.

### Close when
Truth resolution can explain why one source/state is settled while another remains conflicting evidence.

---

## P1-04 — Generalize evidence lineage and dependence graph

### Goal
Extend dependence beyond GHSA-specific deduplication.

### Acceptance criteria
- Evidence can declare upstream/source lineage identity when known.
- Syndicated/republished observations do not become independent votes by source count alone.
- Independent Evidence count is derived from dependence groups.
- Unknown lineage is represented as unknown rather than falsely independent with high confidence.
- GHSA/OSV/SBOM behavior remains compatible.
- Tests include one publisher -> multiple mirrors and two genuinely independent sources.

### Close when
Evidence independence is a reusable model rather than source-specific helpers only.

---

## P1-05 — Detect contradictions automatically and model resolution lifecycle

### Goal
Produce `UNRESOLVED_CONTRADICTION` from conflicting Claims without requiring every adapter to set a manual flag.

### Acceptance criteria
- Same Event/slot overlapping-validity incompatible Claims trigger conflict detection.
- Authority/dependence information is considered.
- Conflict is projected as visible Delta without replacing settled truth.
- Later authoritative evidence can resolve the conflict while preserving history.
- Conflict open/resolved state is replayable and deterministic.
- Gold covers conflict detection and resolution without explicit adapter hint.

### Close when
Cross-source contradiction is a ledger capability, not primarily adapter metadata.

---

## P1-06 — Upgrade Relation to semantic relevance v1

### Goal
Improve `direct / adjacent / reference` beyond exact repository/topic string matching.

### Signals
- Selected repositories and package/repository ancestry.
- User topics and semantic aliases.
- Ecosystem/language/tool relationships.
- Event entities/products/packages.

### Acceptance criteria
- Direct repository/security relations remain deterministic.
- Adjacent semantic matches have an explainable reason and matched concepts.
- False-positive topic matching is evaluated with a labeled relevance set.
- Relation computation remains separate from novelty and importance.
- Per-user data is never used across tenants.

### Close when
Relation evaluation reaches agreed precision target on a fixed personalization Gold set.

---

## P1-07 — Upgrade Importance to impact scoring v1

### Goal
Replace broad source/delta heuristics with event-impact-aware importance.

### Signals
- Correction/conflict.
- Security severity and affected selected repository/package.
- Breaking/deprecation/retirement state.
- Incident impact and recovery state.
- Release type/version significance where structured evidence exists.
- User directness as a separate input, without conflating it with novelty.

### Acceptance criteria
- Importance reason exposes the contributing signals.
- Critical/high are reserved by explicit rules/thresholds.
- Ranking tests include ordering across security, correction, incident, release, and generic publication cases.
- Importance version is persisted or reproducible for replay/debugging.

### Close when
The feed ordering is no longer dominated by source-family defaults.

---

## P1-08 — Upgrade knownness from `delivered == known` to delivered/displayed/read state

### Goal
Model what the user plausibly knows with more fidelity.

### Acceptance criteria
- Distinguish at least `delivered`, `displayed`, and `read` claim state.
- Feed response alone does not permanently suppress an item that was never displayed, subject to bounded retry policy.
- Displayed/read advance user-known watermark according to explicit rules.
- Corrections can still cross the watermark.
- Multi-device retries remain idempotent.
- Migration from existing `user_claim_exposures` preserves current users safely.

### Close when
`K_u` has an explicit state machine and tests for delivered-not-displayed, displayed, read, delayed historical claim, and correction.

---

## P1-09 — Wire Android viewport exposure end to end

### Goal
Ensure actual UI visibility produces exposure records instead of relying on repository capability alone.

### Acceptance criteria
- Feed UI records exposure when an item meaningfully enters the viewport, with debounce/deduplication.
- Exposure carries the delivery ID returned by the corresponding feed response.
- Recomposition/rotation does not generate unbounded duplicate exposure requests.
- Offline/network failure retries safely.
- Android integration test or deterministic UI/viewmodel test proves feed response -> visible item -> `/feed/exposures`.

### Close when
Backend `displayed` state can be trusted to correspond to actual UI display.

---

## P1-10 — Add offline feedback-to-personalization learning v0

### Goal
Use `important` and `not_relevant` feedback to improve Relation/Importance without allowing feedback to rewrite factual truth.

### Acceptance criteria
- Feedback features affect only personalization/ranking layers.
- Training/update is offline or deterministic batch v0, not opaque online mutation.
- Minimum data threshold prevents overfitting to one click.
- Per-user learned state is isolated and resettable.
- Replay of world-state Event/Claim/Delta is unchanged by feedback.
- Evaluation compares ranking/relevance before and after on held-out feedback fixtures.

### Close when
Feedback has a measurable, bounded effect on subsequent feed ranking.

---

# P2 — Reliability, performance, observability, release cut

## P2-01 — Add full-system replay / restart / partial-failure chaos suite

### Goal
Prove the entire pipeline converges, not only individual stores.

### Scenarios
- Duplicate fetch.
- Process restart between Observation and Claim projection.
- Restart between ledger and public projection.
- Out-of-order arrival.
- Delayed correction.
- Source timeout/retry.
- Partial multi-source failure.
- Repeated worker lease expiry/reclaim.

### Acceptance criteria
- Final Event/Claim relations, active Deltas, Evidence, Feed visibility, and knownness are identical to clean replay where semantics should be identical.
- No duplicate meaningful Delta or orphan projection rows.
- Tests run in CI within bounded time.

### Close when
A top-level replay invariant suite covers all major layers together.

---

## P2-02 — Establish performance and SQLite scale baseline

### Goal
Know where the current architecture stops being responsive before production data grows.

### Workloads
- Observation append/replay at 10k/100k scale.
- Event projection with long histories.
- Feed generation for many users/watches.
- Cursor pagination.
- Sync queue claiming.

### Acceptance criteria
- Benchmarks record p50/p95 and DB size for fixed datasets.
- Missing indexes/query hot spots are fixed.
- A regression threshold is stored in CI or a repeatable benchmark script.
- No N+1 source/evidence query causes unbounded API latency on reference dataset.

### Close when
The team has a reproducible capacity baseline and known next scaling boundary.

---

## P2-03 — Add structured observability and audit trail for pipeline decisions

### Goal
Make production semantic errors diagnosable.

### Acceptance criteria
- Structured logs/metrics identify source fetch, Observation ID, Event ID, Claim ID, Delta decision, projection result, and user-feed projection without logging secrets.
- Coreference/revision/authority decisions record reason/version/confidence.
- Counters exist for new observations, novel deltas, non-novel suppressions, conflicts, corrections, projection reconciliations, and sync failures.
- A single Event can be traced from source observation to displayed FeedItem using IDs.
- Private payloads/tokens are excluded from logs.

### Close when
A false merge or missing feed item can be debugged without direct ad-hoc DB archaeology.

---

## P2-04 — Final 90/100 release cut and migration/rollback drill

### Goal
Turn completed implementation into a verifiable release candidate.

### Acceptance criteria
- All issues in this backlog are closed by merged PRs.
- `completion-pr` is up to date with `main` and has no unresolved review threads/blockers.
- Fresh database initialize and upgrade-from-current-schema paths both pass.
- Backup/rollback procedure is documented and exercised on a test DB.
- Gold v0.2 blind gate passes.
- Dependency lock, backend quality, backend security, Android quality all pass on the exact final SHA.
- Final security re-audit includes auth, private Event isolation, source fetch SSRF/rebinding, dependency supply chain, and sensitive logging.
- Completion score review records each layer and demonstrates weighted score >= 90/100.

### Close when
The exact head intended for merge has all evidence above and no subsequent code commits.

---

# Recommended implementation order

1. P0-01 current-head validity.
2. P0-08/P0-09 Gold expansion and blind isolation.
3. P0-02/P0-03/P0-04 Claim normalization + semantic equivalence + revision judge.
4. P0-05/P0-06/P0-07 Event candidate/coreference/repair.
5. P0-10 uncertainty/abstention.
6. P1-01/P1-02 continuous sync + freshness.
7. P1-03/P1-04/P1-05 authority/dependence/conflict.
8. P1-06/P1-07 relevance + importance.
9. P1-08/P1-09 knownness + actual exposure.
10. P1-10 feedback learning.
11. P2-01/P2-02/P2-03 reliability/performance/observability.
12. P2-04 final release cut.

## PR sizing rule

Each issue should normally be closed by **1–2 focused PRs**. If a PR would mix semantic behavior, schema migration, and unrelated UI work, split it. Each semantic behavior PR must add/modify Gold or regression tests before changing production decision logic.