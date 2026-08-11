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

## Configure

The defaults point at one particular machine and will be wrong for you. Override in
your shell profile:

```bash
export FPS_REPO=~/code/your-app        # where forge and shepherd work
export FPS_PILOT_DIR=~/code/your-app   # where pilot starts, if different
export FPS_DB=~/path/to/fps.db         # open-loop + learning-queue database
```

Then create the database tables once:

```bash
fps-loops init
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
