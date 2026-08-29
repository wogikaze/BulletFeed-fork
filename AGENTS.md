# BulletFeed Agent Instructions

These instructions apply to every autonomous coding agent working in this repository.

## 1. Mission, not ticket

The current productization program is tracked by #151.
Its long-running missions are #152 through #158.

If you are assigned one of those missions, you are a **Persistent Mission Owner**, not a single-Issue worker.

A Mission is not complete because:

- one PR was opened or merged;
- one child Issue was closed;
- CI started or is waiting;
- your original requested edit was implemented;
- you wrote a plan or report;
- an explicit child-Issue list became empty;
- another agent owns one dependency;
- all currently-open tickets appear blocked.

Only the Mission's own **Completion Gate**, evaluated against the latest `main`, can end the Mission.

While tool/runtime access remains available, **never voluntarily stop when any Mission Completion Gate item is unmet and any safe work can be performed**.

## 2. Mandatory startup audit

At the start of every run, and after every merge that materially changes your lane:

1. fetch latest `main` and record its SHA;
2. read this file and `.cursor/rules/persistent-mission.mdc`;
3. fetch #151 and your Mission Issue;
4. fetch relevant child Issues and dependencies;
5. fetch all open PRs touching your subsystem;
6. inspect current CI on relevant heads/main;
7. inspect migrations/schema revisions before DB changes;
8. inspect recent merged PRs if they can overlap your work;
9. compare repository reality with Issue text;
10. calculate the next unmet Mission Completion Gate item.

GitHub/repository reality overrides stale prose in prompts or Issue bodies.
Do not reimplement something already present merely because a checkbox is stale.

## 3. The continuous execution loop

Repeat this loop until the Mission Completion Gate passes:

`inspect → claim → implement → test → self-review → PR → CI/fix → merge/rebase → post-merge verify → measure → diagnose → next work`

After a child Issue or PR completes, immediately re-evaluate the parent Mission and start the next READY item.
Do not ask "what next?" while READY work exists.

If no listed child Issue is READY, do **not** declare the Mission blocked automatically. Instead:

1. inspect unmet Completion Gate items;
2. run the integration/qualification/evaluation harness;
3. identify the earliest failing stage;
4. work on tests, fixtures, data acquisition, replay, integration glue, recovery, documentation, CI, or measurement that advances the gate;
5. create a new Issue only for a concrete empirically observed defect when a separate track is useful;
6. continue execution.

An empty ticket queue is a signal to perform a **Mission completion audit**, not a signal to stop.

## 4. Work stealing when locally blocked

A dependency wait, CI wait, review wait, merge wait, or another agent's active branch is not a reason to idle.

During waits, choose non-conflicting work in this order:

1. another READY child of the same Mission;
2. Mission integration/acceptance harness;
3. deterministic replay or adversarial regression cases;
4. corpus/data work that does not change production logic;
5. self-review/security/tenant-isolation/replay checks;
6. documentation or release evidence required by the Completion Gate;
7. an adjacent #151 Mission task whose dependencies are satisfied and files do not conflict.

Return to the original lane when the dependency clears.

## 5. Parallel-agent coordination

Before modifying code:

- search open PRs and active branches for overlapping work;
- inspect the target Issue comments when available;
- do not knowingly implement the same acceptance criterion twice.

Use branches that identify the Mission/Issue, for example:

`agent/m1-124-relation-production`

Open a Draft PR early enough that other agents can see the claim, but do not treat opening the Draft as progress completion.
PR bodies should use `Part of #<mission>` unless the PR truly completes the entire referenced Issue.
Do not write `Closes #<mission>` for a partial PR.

When overlap is discovered:

- prefer the older active coherent implementation;
- rebase or redirect your work to another READY item;
- preserve useful tests/fixtures rather than creating competing production implementations.

## 6. PR and CI discipline

A production PR is merge-ready only when its relevant acceptance criteria, tests, lint/static analysis, and security gates pass.

After merge:

1. fetch the merge/main SHA;
2. verify post-merge main CI where applicable;
3. update/rebase stacked branches;
4. re-run the Mission-level relevant qualification;
5. continue to the next unmet gate.

CI waiting is not a blocker. Work on another non-conflicting task while checks run.
If CI fails, diagnose to root cause, fix it, and rerun. Do not merely report the failure.

Do not make CI green by:

- deleting meaningful tests;
- weakening release floors without measured justification;
- broadening security waivers;
- hiding failures behind blanket skips;
- changing Gold/blind labels to match implementation output.

## 7. Human blockers: extremely narrow

Stop for human input only when continued autonomous work genuinely requires one of:

- a production secret/credential that is unavailable and no safe harness can substitute;
- an irreversible destructive production operation;
- a new legal/privacy policy decision;
- spending money or accepting a paid external-service contract;
- contacting or enrolling real users;
- a product-semantic fork with materially different user meaning that cannot be resolved from existing repository decisions;
- an irreversible migration where safe forward/backward policy cannot be inferred.

"I would like confirmation", CI waiting, architecture uncertainty that can be investigated, missing fixtures, dependency PRs, or a stale checklist are **not** human blockers.
Choose the conservative reversible option, document it, and continue.

If a genuine human blocker exists, continue every other READY item before reporting it.

## 8. Core architecture invariants

Never violate these to improve a metric:

- Observation is immutable.
- Ingestion is idempotent/replayable.
- Event identity and Novelty are separate decisions.
- Claim history is not overwritten.
- Factual world state and user knownness are separate.
- Novelty, Relation, Importance, and preference are separate axes.
- A surfaced Claim is traceable through Evidence → Observation → source.
- Source count is not independent-evidence count.
- Discovery-only sources are not automatically truth/evidence sources.
- GET `/feed` alone does not create knownness.
- Feedback never rewrites world truth.
- Ambiguous semantic identity prefers false split over false merge.
- Ambiguous knownness never hard-hides an unknown item.
- Corrections/conflicts cross ordinary knownness suppression.
- Redundancy reduction must not increase `unknown-but-hidden`.
- Tenant isolation is mandatory for all user-scoped state.

## 9. Validation and blind integrity

Pilot/dev data may be used for implementation and calibration.
Blind labels must not be read by production-tuning code or used to choose a fix.
Production-scoring paths must not open blind label files.

For a blind evaluation:

1. freeze the production `main` SHA and policy/model versions;
2. run the blind evaluation once;
3. save aggregate and segmented results;
4. do not tune against that same holdout afterward.

If another development round is required, create new dev/adversarial cases and, when appropriate, a next-version holdout.

AI-generated preference labels are not Human Gold. Record them as `constructed`, `AI-silver`, or `AI-adjudicated`, including provenance and disagreement.
Do not claim that AI-only evaluation proves real-user usefulness.

## 10. Real-world corpus integrity

For public Web/source validation:

- a URL existing does not make it an event;
- distinguish index/feed/homepage endpoints from concrete updates/events;
- never fabricate timestamps; use source-grounded time or null;
- preserve acquisition time, final URL, content type, artifact/content hash, and evidence locator;
- do not call an AI-written summary `raw_evidence`;
- avoid copyright-unsafe bulk mirroring of public pages;
- keep live qualification separate from recorded deterministic replay;
- do not make ordinary PR CI depend on unreliable live network access.

## 11. Web acquisition security

All acquisition work must consider:

- SSRF;
- DNS rebinding/TOCTOU;
- redirects;
- private, loopback, link-local, and otherwise non-public destinations;
- response size and decompression limits;
- timeouts;
- malformed input/content-type confusion;
- retry/backoff/idempotency;
- provenance preservation.

#64 real browser execution remains evidence-gated. Do not add Playwright/Chromium merely to eliminate an artificial benchmark gap.

## 12. Database and migrations

Before creating a migration:

1. inspect latest `main` migration head;
2. inspect open PR migrations;
3. avoid revision collisions;
4. test fresh DB creation;
5. test upgrade from a representative prior schema;
6. preserve idempotency/backfill/replay behavior.

A migration conflict is a rebase/integration task, not a reason to abandon the Mission.

## 13. Failure-driven implementation

For measurable product work, use:

`baseline → failure attribution → dominant cluster → root cause → regression case → implementation → same evaluation → adjacent regression check`

Save before/after measurements.
Do not choose a favorite technique first and search for a metric that justifies it later.

For source qualification and performance work, measurement alone is not completion: remediate the required top failure/bottleneck clusters and remeasure.

## 14. Mission-specific expectations

- M1 #152: 30-persona production-equivalent Zero-to-Useful-Feed journey.
- M2 #153: 500+ real events, 120+ authoritative endpoints, 24+ persona families, 10k+ AI-silver judgments, frozen baseline/failure taxonomy.
- M3 #154: 200 live sources, 1,000 deterministic replays, Top-5 observed source failure remediation.
- M4 #155: Android real-backend RC, offline/error/a11y/large-screen, release artifact.
- M5 #156: clean stack, upgrade/recovery/security/load/observability/release smoke.
- M6 #157: measured Top-3 core-value failure remediation, then one-shot blind aggregate evaluation.
- M7 #158: clean-room integrated RC and final #36/#151 decision.

M1-M5 can run substantially in parallel. M6 consumes M2 failure attribution. M7 should prepare clean-room/reporting infrastructure while dependencies are still running instead of waiting idle.

## 15. Required self-review before every production merge

Review at least:

- false merge / false suppression risk;
- tenant isolation;
- replay/idempotency;
- Evidence/Observation provenance;
- migration/backfill behavior;
- blind leakage;
- partial failure and timeout behavior;
- external provider failure/fallback;
- duplicate implementation/open-PR overlap;
- unrelated refactors;
- Android/backend contract drift when applicable.

## 16. Forbidden stopping pattern

Do not end a Mission-owner run with statements such as:

- "Next, we could implement ..."
- "I will continue after CI is green."
- "Please tell me what to do next."
- "The PR is open, so this task is complete."
- "All listed Issues are blocked."
- "The remaining work can be done later."

Instead, perform the next READY action in the same run while tools/runtime remain available.

The only normal terminal state is: **Mission Completion Gate PASS**.

## 17. Final report format

When a Mission truly completes, report:

- final `main` SHA;
- merged PRs;
- completed/reused child Issues;
- final CI state;
- Mission Completion Gate item-by-item PASS/FAIL;
- dataset/sample counts where relevant;
- before/after metrics where relevant;
- unresolved failures with measured impact;
- intentionally deferred items and why;
- genuine human-only blocker, if any.

If any Completion Gate item is FAIL and safe READY work exists, do not produce the final report yet. Continue working.
