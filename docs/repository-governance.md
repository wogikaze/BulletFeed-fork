# Repository governance and protected release branch

`BulletFeed-fork` treats CI evidence as a merge invariant, not as an advisory signal. Workflow YAML can produce evidence, but it cannot by itself stop an administrator or direct pusher from bypassing checks. GitHub repository rules for `main` must enforce the controls below.

## Required `main` ruleset

Target: branch `main`.

Required controls:

- restrict normal updates to pull requests;
- block force pushes;
- block branch deletion;
- require the branch to be up to date before merge, or use merge queue so checks run against the merge result;
- require all selected status checks to succeed before merge;
- do not treat failed or skipped required checks as success;
- include administrators in normal enforcement; emergency bypass must be intentional and audited.

Core pre-merge checks emitted by the current fork workflows:

| Workflow | Required job/check |
| --- | --- |
| Backend quality | `Ruff and pytest` |
| Backend security | `Dependency and static security audit` |
| Dependency lock | `Verify hash-locked Python dependencies` |
| Android quality | `Lint and format check` (depends on `Lint, format and unit tests`) |
| Backend Docker build | `Build backend Docker image` |

`SQLite capacity boundary / Validate SQLite single-writer boundary` is a path-scoped qualification check and should gate changes that touch its benchmark/storage-critical paths; it is not a global required context while its workflow is path-scoped. `M5 host recovery drill / Docker API and worker restart drill` remains an explicit release/operations drill because it is manually dispatched rather than a normal PR check.

GitHub may display a context as `Workflow name / Job name`; select an observed context emitted by this repository, not an invented free-form name.

## PR trigger invariant

A check cannot protect a PR if its workflow runs only after pushing to `main`. Android quality, Backend Docker build, and Dependency lock therefore include `pull_request` triggers in addition to their existing main-push behavior. Backend quality and Backend security already run on pull requests.

If a future required workflow becomes path-scoped, either provide a stable always-running aggregator check or remove it from the global ruleset. Do not configure a required context that can remain permanently absent on unrelated pull requests.

## Review policy

For a single-maintainer repository, requiring another person's approval can make routine maintenance impossible. The minimum safe policy is:

1. every normal change enters `main` through a pull request;
2. every required automated check passes on the merge result/up-to-date head;
3. unresolved review threads block merge when reviews are present;
4. when another maintainer is available, require at least one approval for security-sensitive or release-governance changes.

If multiple maintainers become regular contributors, raise the repository rule to at least one required approving review and dismiss stale approvals when new commits are pushed.

## Emergency bypass

A bypass is for repository recovery when the normal rule itself prevents repair, not for shortening CI time.

For every bypass:

1. record an issue describing the incident and why the normal merge path was impossible;
2. record the exact before/after SHA and actor;
3. make the smallest repair possible;
4. run all normally required checks on the resulting exact `main` SHA;
5. restore/enforce the ruleset immediately after repair;
6. link exact workflow run IDs in the incident issue.

Prefer an auditable forward fix over force-rewriting `main` merely to erase a harmless commit.

## Verification drill

After the ruleset is configured, prove enforcement rather than relying on the settings screen:

1. open a temporary PR that intentionally fails one required check;
2. confirm GitHub refuses to merge it;
3. repair the PR and allow all required checks to pass;
4. confirm merge becomes available only after required up-to-date/merge-result checks are green;
5. record the exact PR, SHA, and workflow runs as governance evidence.

## Current administrative state

Audit on 2026-09-13 found the fork ruleset collection empty and `main` reporting `protected: false`. The repository code in this port supplies the missing pre-merge workflow triggers and the policy, but branch/ruleset enforcement is an external GitHub repository-administration setting. Do not claim protected-branch enforcement until the verification drill above succeeds.
