---
name: my-review
description: Personal branch review. Runs the repaired 11-reviewer lineup plus a mechanical prior-art gate and a framework-seam check. Use for "my review", "personal review", "review this branch properly". Distinct from the team's /review-branch.
---

# Personal branch review

The team's `/review-branch` lineup has four reviewers pointing at agent types that do not
exist (`performance-engineer`, `security-engineer`, `quality-engineer` twice), so Performance,
Security, Code Quality, and Spec Compliance are degraded or absent. This skill runs a repaired
lineup plus two gates covering the failure modes that reach human review most often.

## Step 0 — is CI even running?

Before anything else, and before ever calling a branch green:

```
bash ~/.claude/skills/ci-reality-check/bin/ci-check.sh <pr>
```

A stacked PR does not run the test suite at all — the workflow only fires for PRs targeting
master — and the PR still shows a green tick from the no-op checks. Treat `NO-CI` as "the suite
has never run", not as a pass. See the `ci-reality-check` skill.

## Step 1 — prepare

```
git diff master...HEAD --stat
```

If the branch is behind master, say so before reviewing — stale diffs produce phantom findings.

## Step 2 — spawn all reviewers in parallel

One message, many Agent calls. Every reviewer gets the same instruction: review
`git diff master...HEAD`, return findings as Critical / Warning / Info with `file:line`.

| # | Focus | subagent_type |
|---|-------|---------------|
| 1 | **Prior art / reuse** | `prior-art-gate` |
| 2 | **Framework seam** | `framework-seam-reviewer` |
| 3 | **Query performance** | `perf-query-reviewer` |
| 4 | **Correctness** | `correctness-reviewer` |
| 5 | Security | `security-reviewer` |
| 6 | Multi-tenancy | `multi-tenancy-auditor` |
| 7 | Test gaps | `test-gap-analyzer` |
| 8 | Design system | `design-system-reviewer` |
| 9 | Maintainability | `maintainability-balanced` |
| 10 | Silent failures | `pr-review-toolkit:silent-failure-hunter` |
| 11 | Comment style | `pr-review-toolkit:comment-analyzer` |

Rows 1–4 are the repaired/new slots. Rows 5–7 exist in the repo but are unused or opt-in in
the team lineup.

Row 9 is `maintainability-balanced`, not the team's `maintainability-reviewer`. The team version's
premature-abstraction rule flags "base classes or concerns introduced for a single caller", which
fires on exactly the seam adoption row 2 exists to demand. The personal variant scopes that rule to
*newly invented* abstractions so the two reviewers stop cancelling each other out.

## Step 3 — synthesise

- **The prior-art gate's output is not optional reading.** It reports the searches it ran for
  every new named thing, including clean results. A `NO PRIOR ART FOUND` with three searches
  attached is a real result; a missing block means the gate did not run properly.
- Deduplicate findings that several reviewers raise; keep the one with the best evidence.
- Rank Critical first. Every Critical needs a concrete failure scenario — inputs or state, and
  the wrong result. Downgrade anything that cannot state one.

## Step 4 — report

Group by severity, not by reviewer. For each finding: `file:line`, one-sentence defect, the
failure scenario, and the fix. Note explicitly which reviewers came back clean.

Never post findings anywhere. Report in the terminal and stop.
