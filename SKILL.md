---
name: fps
description: Use when setting up or reasoning about the Forge / Pilot / Shepherd session split — three concurrently-open Claude sessions with fixed, separate jobs (build, orient, land). Covers launching the tabs, the role charters, and the open-loop tracker. Invoke when asked "set up my tabs", "which tab should this go in", or when work is drifting into the wrong session.
allowed-tools: Bash, Read, Edit, Write
version: 1.0.0
---

# FPS — Forge, Pilot, Shepherd, Warden, Mentor

Five Claude sessions open at once, each with a fixed job and an explicit list of things it
does not do.

| | forge 🟢 | pilot 🔵 | shepherd 🔴 | warden 🟣 | mentor 🩵 |
|---|---|---|---|---|---|
| Job | build and research | keep you oriented | land what exists | watch the machine | turn work into understanding |
| Produces | draft PRs | decisions and answers | merged work | notices | explanations |
| Never | marks ready, lands | writes app code, orchestrates | starts new work | fixes app code, restarts things | writes code, pads, flatters |

Tab order left to right is forge, pilot, shepherd, warden, mentor — roughly the direction
work travels, with the environment watcher and the teacher at the end.

## Why roles rather than parallel tasks

Nearly every published multi-session setup is *task*-parallel: N sessions on N tickets. That
pattern reliably hits the review queue as its ceiling — generation parallelises, human
review does not.

Role separation is cheaper because the three sessions produce **different output types**.
Only forge generates diff. pilot produces answers; shepherd produces review responses and
merges. They do not compete for the same scarce resource.

The cost is different too: the risk is not throughput, it is **drift** — whichever session
happens to be focused absorbing whatever you just thought of. The charters exist for that,
and it is the failure to watch for.

## Run it

```bash
fps                 # every role plus a plain shell, as iTerm2 tabs
fps forge           # one tab in the current window
fps pilot --here    # take over this shell, no new tabs
fps code            # a VS Code workspace, one coloured profile per role
fps mine            # open the project in RubyMine
```

### Other editors

`fps code` writes `~/.fps/fps.code-workspace` — outside the repository, so nothing is added
to the project — and opens it.

Roles arrive two ways, because each covers the other's gap. **Tasks** open every role
automatically when the workspace opens, each with a coloured icon. **Profiles** sit in the
terminal dropdown for starting one by hand later.

The first open asks whether to allow automatic tasks; that prompt is what starts the role
terminals, and declining leaves the profiles working. VS Code takes theme colour ids rather
than RGB, so the colours are the nearest ansi equivalents.

`fps mine` opens the project in RubyMine and prints the role commands. Its terminal has no
per-tab colour — the colours elsewhere come from an iTerm escape code and a VS Code profile,
and JetBrains has neither — so roles start with `fps <role> --here` in any terminal tab.

Each tab colours itself, moves to the role's home directory, prints a short brief, then
launches Claude with the role charter appended to its **system prompt** — not sent as a
first message, so it cannot scroll out of the conversation.

## The shell tab

`fps` also opens a sixth, uncoloured tab: a plain login shell in the same directory, with no
Claude session in it. Somewhere to run a command without interrupting one of the five, and
without a session to clean up afterwards. It prints two lines and gets out of the way —
`whereami` is there if state is wanted.

```bash
fps shell           # just the shell
```

## Which repo

FPS is not tied to any one project. A session binds to a repo when it starts, and
that binding is fixed for the rest of its life:

```bash
fps forge                      # the git root of the current directory
fps forge --repo ~/code/app    # somewhere else
fps repos                      # every repo that has joined
```

Each repo gets its own database of notices and open loops, created on first use at
`~/.fps/dbs/<basename>-<hash>.db` — never inside the repo itself. The basename makes
the file recognisable; the path hash keeps two checkouts sharing a basename apart.

Lessons (`fps-learn`) and the standup tables stay in one global database on purpose.
They belong to the person, not the project, and the learning queue is specifically the
thing meant to outlive any one job.

A session cannot change repo once it has started. `--repo` naming a different project
is an error, not a switch — otherwise a long session could quietly start writing into
another project's queue halfway through.

Optional per-repo settings go in `~/.fps/config/<slug>.json` (`pilot_dir`, `ports`),
kept outside the target repo so an app repo that ships to a team stays clean.

```bash
export FPS_REPO=~/code/your-app        # a default when you are not inside the repo
export FPS_PILOT_DIR=~/code/your-app   # where pilot starts, if different
export FPS_NOTICE_TTL_DAYS=14          # how long an unacked notice is delivered
```

A directory that does not exist is a hard error naming what to set, rather than a silent
`cd` to nowhere.

## Running a role under Hermes instead

`FPS_AGENT=hermes fps <role>` launches the same role under Hermes rather than Claude
Code. Everything before the launch is identical — the tab colour, the directory, the
brief, the notices and the open loops are the same job whoever answers.

The charter reaches the two agents differently. Claude Code takes it as a file on every
launch; Hermes reads `SOUL.md` from its profile, so `fps-tab` **writes the charter into
that file at launch**, replacing what it wrote last time. There is no sync step and no
rule to remember, because a step you have to remember is a step that gets skipped, and a
guard that checks the charter is merely *present* passes on a stale one.

**mentor does not run under Hermes**, and `fps-tab` refuses it. mentor gates a lesson on
the human predicting the answer, enforced with `--prompt-suggestions=false`, and Hermes
has no equivalent — a Hermes mentor would hand over the answer it exists to withhold. Its
charter also dispatches a Claude Code skill.

Create a profile with `hermes profile create <role> --no-alias`. The alias would put a
bare `forge` on your PATH, which is a second way to start a role that FPS already starts.

`fps-services sessions` lists both agents, and names the agent only when both are
running. Liveness is asked of the process rather than of either agent's session store,
because a record outlives the thing it describes and a pid that answers does not.

## The charters

`charters/{forge,pilot,shepherd,warden}.md`. Keep them short. Instruction-following degrades as
context grows, and the degradation is uniform — a bloated charter weakens rules that used
to work, including ones in other files. If a rule is being ignored, the fix is usually to
cut the file, not to restate the rule louder.

The single most important line in the set is pilot's ban on orchestrating the other
sessions. A coordinator role with nothing to build reliably invents coordination to do:
the documented version of this had an agent invent twenty organisational roles while
actual work stopped. pilot holds state and hands it back. That is the entire job.

## How the sessions reach each other

Each tab launches with `--name <role>`, so every running session appears in
`~/.claude/sessions/` with its role, working directory, and pid. `fps-services sessions`
lists the live ones — session files are not reaped, so liveness is decided by whether the
pid still answers.

warden leaves notices; every tab collects the ones addressed to it **when it starts**:

```bash
fps-services notify --what "postgres is down" --for forge --severity error
```

Delivery is deliberately at session start rather than pushed mid-conversation. A message
that interrupts is a message that gets dismissed; one waiting at the top of a new session
is read. The cost is latency — a notice waits for the next launch — which is the right
trade for everything except an emergency, and an emergency is worth saying out loud.

Notices carry **facts, not context**: what is broken and what it blocks. A reviewer works
better without the builder's context, and the same holds here — the PR, the issue, and the
logs carry the why.

**This is enforced at 400 characters, not asked for.** It was asked for first, and of the
first 45 notices sent the median body ran 1,351 characters. On 2026-09-06 twelve of the
fifteen unacked in forge's queue were specs; three of them asked for the same build on
three separate days and none became a bead. A spec in a notice cannot be sequenced,
depended on, superseded or closed, so it sits there being redelivered until it is
wallpaper. `notify` now refuses anything longer and prints the `bd create` to use instead.

## The learning queue

Any session pushes something worth understanding and carries on:

```bash
fps-learn add --topic "..." --why "one to three sentences" \
              --level senior|staff|both --source REF --from <role>
fps-learn list          # what is queued
fps-learn show ID
fps-learn studied ID
```

mentor opens with the queue, lists it with a short why on each, and goes deep only when
asked. Capture is deliberately zero-decision — deciding whether something matters is
mentor's job later, not the pushing session's job now. Categorising at capture time is what
kills these queues.

Lessons attached to a real incident outlast lessons from a list of best practice, so prefer
what the work actually surfaced.

## Open loops

```bash
fps-loops add --who NAME --what "question" [--where URL] [--asked-at ISO]
fps-loops list
fps-loops close ID
```

An open loop is a question asked of a person that never came back. Nothing else in the
stack holds these — the issue tracker holds work, git holds code, the calendar holds time —
so they rot silently. Anything unanswered for three days is flagged stale.

One table, in the existing standup database. Cross-session coordination deliberately is
**not** stored here: Claude Code has session messaging built in, and every reported
multi-agent setup that added a shared-state file watched it decay into archaeology.

## Design rules this follows

**The brief is short and ends in one thing.** A tab brief you stop reading is worse than
none, because it trains you to skip it. If it grows past a few seconds of reading, cut it.

**No streak counters, no completion percentages, no "you haven't done this in N days."**
The documented way these systems die is guilt about a gap, not the gap itself. Missing a
day has to cost nothing.

**Nudges ride attention you are already spending** rather than competing for it. A prompt
you were going to read anyway beats a notification you learn to dismiss.

**Nothing here is required for the work to proceed.** Every piece is optional and additive.
A tool you must remember to use, that punishes you for not using it, will be abandoned.

## Kill criterion

Apply this honestly, on a schedule: **if a piece of this stopped working a month ago and
you did not notice, it was not producing anything.** Delete it.

The specific risk with this system is that it is infinitely tweakable, which makes it an
excellent procrastination target — the same flexibility that lets it fit you is the thing
most likely to consume the time it was meant to protect. Changes to FPS are work like any
other work, and they compete with the actual job.
