---
name: qa-gate
description: Use before any push, and whenever asked "is this ready", "run the gate", "QA this branch", or "check it passes everything first". Emits one PASS/FAIL verdict plus failing evidence for any repo, in any language. Warden runs it and reports; it never repairs what it finds.
---

# QA Gate

A gate, not a report. It ends in one word — PASS or FAIL — and the evidence for a
FAIL. If you find yourself writing a nuanced summary, you have written the wrong
artifact.

```bash
~/.claude/skills/qa-gate/qa-gate.sh [repo]     # exit 0 = PASS, 1 = FAIL, 2 = could not run
~/.claude/skills/qa-gate/qa-gate.sh --list     # what would run here
```

## A PASS does not authorize a push

**"Gate green" means "ready for Alex to test". It never means "ready to push".**

Alex personally drives every change before it goes up. The gate is necessary and not
sufficient — it proves the machine-checkable things hold, which is a different claim
from "this works". Do not treat a PASS as approval, and do not offer to push on the
strength of one.

## Which Python it runs

Resolved once, newest first, and printed with the verdict. Bare `python3` is whatever
PATH names, and on macOS a minimal PATH names `/usr/bin/python3`, which is 3.9.6 and has
no `tomllib`. Measured 2026-09-07: the gate PASSED jobhunt from an interactive shell and
FAILED the same repo from the same commit under a hook's PATH, because homebrew sorts
first in one and not the other.

A verdict that depends on the caller's environment is not a verdict, so the interpreter
is now named in the output. Override it with `QA_GATE_PYTHON` when a repo needs a
specific one.

## Warden runs it; warden does not fix it

Warden's charter is to report and never to repair application code. That holds here.

- Warden runs the gate and emits the verdict as a notice to forge or shepherd:
  `fps-services notify --what "qa-gate FAIL on <repo>/<branch>: <check> — <detail>" --for forge`
- Warden does not edit code to make a check pass. A gate that repairs what it finds
  cannot be trusted to report, because it has a stake in the answer.
- Forge or shepherd fixes; warden re-runs.

## What it checks

Project type is **detected**, never assumed — ruby by Gemfile, node by package.json,
swift by Package.swift, python by layout.

| Check | FAIL when |
|---|---|
| tests | the suite is red |
| lint | the configured linter complains; with none installed, syntax must still parse |
| secrets | a credential pattern appears in a tracked file |
| gitignore | anything the repo's own `.gitignore` claims to ignore is *tracked*, or a backup/credential-shaped file is |
| smoke | the entry point cannot run `--help` |
| dependency promise | the README promises stdlib-only / no-dependencies and an import breaks it |

The dependency promise is the highest-value check and the least obvious. jobhunt's
README says "stdlib only, no dependencies, no install step". Nothing verified that, so
one `import requests` would have made the README false without failing anything. **A
documented promise that nothing enforces is a promise that decays.** When you add a
promise to a README, add its check here in the same commit.

`gitignore` asks git, not the file — a rule added after a file was already tracked ignores
nothing. It derives the path list from the repo's own `.gitignore` rather than a fixed set:
a hardcoded list has to be edited every time a repo gains a secret, and until someone does,
it reports a clean bill for everything it was never told about. Backup variants are swept
separately, because an ignore rule for `profile.toml` does not cover `profile.toml.bak` —
that exact gap had to be caught by hand twice.

## Extending it

Add checks to `qa-gate.sh`, not to this file. The script is the gate; this file
explains it. Every check must:

1. Emit exactly one of PASS / FAIL / SKIP, with a reason on SKIP.
2. Be silent about repos it does not apply to — a SKIP is honest, an invented PASS is not.
3. Never mutate the repo. No formatters in write mode, no `--fix`, no installs.

**SKIP is not PASS.** A SKIP means nothing checked that. If a repo is skipping most of
the gate, say so out loud rather than reporting a clean run.

## Classification rule, inherited from the team's qa-plan

**A scenario is only [HUMAN] if no simulation, API call, or browser session can produce
the same event.** Most "manual" QA is not. Before writing "manually verify X", ask what
would generate the real event — a request, a fixture, a provider's own API, a headless
browser. Perception (audio, visual judgment, a display you cannot read) and actions only
their devices can take are what remain.

## Operational traps

| Trap | Countermeasure |
|---|---|
| The suite is green but the change is not live — a shim, symlink, plugin cache or installed copy is what actually executes | Resolve the entry point before believing a green run: `command -v`, `readlink -f`, and read the shim. Then run the real command and watch the new behaviour |
| A negative test injects bad state, the injection silently no-ops, and the guard "passes" having never seen a failing input | Assert the precondition landed — print the resolved value — before trusting the result |
| A linter is not installed, so lint "passes" | No linter is a SKIP or a syntax-only PASS, never a clean bill |
| `.gitignore` lists a path that is already tracked | Ask git (`git ls-files <path>`), not the ignore file |
| Async side effects are asserted immediately after enqueue | Poll with a deadline; not-yet is not failure |
| A long-lived dev process predates the code under test and runs stale logic | Compare process start time to the last edit; restart first, debug second |
| A run is called clean when most checks skipped | Report the SKIP count with the verdict |
| A check's PASS message is broader than what the check actually tests — "sensitive paths are untracked" while testing a hardcoded seven-path list | Derive the check's scope from the repo, not from a list in the checker. Where that is impossible, narrow the wording until it matches the coverage exactly |

## Red flags — stop

- Reporting PASS when checks were skipped, without saying which
- Editing code so the gate goes green, while running as warden
- Offering to push because the gate passed
- Writing "manually test X" for something a script could drive
- Adding a check that mutates the repo

## Retrospective

When a gate run surprises you — a false PASS, a false FAIL, a check that should have
existed — add the trap to the table above and the check to `qa-gate.sh`, then say in one
sentence what changed. A run that teaches nothing is fine. Skipping this when something
did surprise you is how the gate rots.
