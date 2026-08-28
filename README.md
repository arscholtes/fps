# FPS — Forge, Pilot, Shepherd, Warden, Mentor

Five Claude Code sessions open at once, each with a fixed job and an explicit list of
things it does not do. Full documentation, design rationale, and the command reference
live in [SKILL.md](SKILL.md) — this file is just setup.

| | forge 🟢 | pilot 🔵 | shepherd 🔴 | warden 🟣 | mentor 🩵 |
|---|---|---|---|---|---|
| Job | build and research | keep you oriented | land what exists | watch the machine | turn work into understanding |
| Produces | draft PRs | decisions and answers | merged work | notices | explanations |
| Never | marks ready, lands | writes app code, orchestrates | starts new work | fixes app code, restarts things | writes code, pads, flatters |

## Requirements

- macOS (tab colouring and `fps code`/`fps mine` assume it; iTerm2 for the tab launcher)
- Claude Code CLI
- Python 3 (ships with macOS)

## Install

```bash
git clone <this-repo> ~/Developer/fps
~/Developer/fps/install.sh
```

The installer writes four thin shims into `~/.local/bin` (`fps`, `fps-services`,
`fps-learn`, `fps-loops`) pointing at this clone, and symlinks the repo into
`~/.claude/skills/fps` so Claude Code picks it up as a skill. Make sure
`~/.local/bin` is on your `PATH`.

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

A repo joining for the first time can have its own notes written for it:

```bash
fps-bootstrap                  # print what it learned
fps-bootstrap --write          # notes, plus a CLAUDE.md if the repo has none
```

It records only what it observed and lists what it could not determine as an
explicit gap — a confident wrong answer in a CLAUDE.md is worse than a blank,
because every session downstream acts on it. It never overwrites a CLAUDE.md
that already exists.

Optional per-repo settings go in `~/.fps/config/<slug>.json` (`pilot_dir`, `ports`),
kept outside the target repo so an app repo that ships to a team stays clean.

```bash
export FPS_REPO=~/code/your-app        # a default when you are not inside the repo
export FPS_PILOT_DIR=~/code/your-app   # where pilot starts, if different
export FPS_NOTICE_TTL_DAYS=14          # how long an unacked notice is delivered
```

## Run

```bash
fps                 # every role plus a plain shell, as iTerm2 tabs
fps forge           # one tab in the current window
fps pilot --here    # take over this shell, no new tabs
fps code            # a VS Code workspace, one coloured profile per role
fps mine            # open the project in RubyMine
```

The role charters are in [charters/](charters/) — read them, then rewrite them for
your own project. They are the system; everything else is plumbing.
