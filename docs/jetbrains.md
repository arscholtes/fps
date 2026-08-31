# FPS on JetBrains — design notes

Research pass, 2026-08-28. Nothing here is built yet.

Alex uses JetBrains IDEs exclusively. FPS today assumes iTerm2 and, failing that,
VS Code. This is what it would take to make JetBrains the primary host, what FPS
gains that a terminal cannot give it, and the one constraint that has to be
settled before any of it ships.

## Where FPS stands today

| command | what it does |
|---|---|
| `fps` | six iTerm2 tabs — five roles plus a shell, coloured by `fps-tab` escape codes |
| `fps <role>` | one role in a new iTerm2 tab |
| `fps <role> --here` | takes over the current shell — **the seam everything else builds on** |
| `fps code` | writes `~/.fps/fps.code-workspace` and opens VS Code |
| `fps mine` | opens the project in RubyMine — and nothing else; no sessions |

`fps mine` is the honest summary of the problem. It opens an editor next to the
work instead of hosting it.

`--here` is the important detail: every host is just a way to arrange shells that
each run `fps <role> --here`. A JetBrains host needs no new session machinery.

## The mechanism

**Shell Script run configurations**, in Script Text mode, with **"Execute in the
terminal"** checked. That option runs the command in the Terminal tool window
rather than the Run tool window, which is the difference between a role tab and a
process output pane. Each configuration carries its own working directory and
environment. A **Compound** configuration launches several in parallel.

So: five configurations (`fps-forge` … `fps-mentor`), each running
`fps <role> --here` in that role's home directory, plus one compound `fps` that
starts them together. Written to `.idea/runConfigurations/` in the target repo.

Confirmed from JetBrains' own documentation. **Not yet confirmed:** the exact XML
element names (`ShConfigurationType`, `EXECUTE_IN_TERMINAL`, `SCRIPT_TEXT`). There
are no existing run configurations on this machine to pattern-match, so the first
generated file is the test. Generate one, open the IDE, see whether it appears in
the Run dropdown — that is the whole verification.

## What JetBrains gives FPS that iTerm cannot

This is the part that makes the move worth more than tab cosmetics.

Every installed IDE is 2025.2 or newer (IntelliJ IDEA 2025.3.3 Ultimate, RubyMine
2026.1.2, PyCharm 2025.3.3, DataGrip 2025.3.5), which is the version where
JetBrains began bundling an **MCP server**. `claude-code-jetbrains-plugin` is
already installed in RubyMine and PyCharm. A Claude Code session running in the
IDE terminal connects to it automatically and gains:

- the **active file and current selection** as context on every prompt
- **native diff viewer** instead of printing a diff into a terminal
- the IDE's **inspection diagnostics**, readable by the session

Those map onto the roles unevenly, which is the interesting bit:

- **warden** watches services and logs. Inspections are a second, structurally
  different signal it currently has no access to.
- **forge** hands off draft PRs. Opening a real diff beats printing one.
- **shepherd** works through review feedback against specific lines. Selection
  context is exactly its input.
- **pilot** and **mentor** gain least — they are mostly conversational.

None of this requires FPS to do anything. It follows from the session running
inside the IDE. It is the strongest argument for the move.

## Per-repo IDE selection

FPS is being made repo-targetable (see the retargeting and multi-tenant notes in
the queue). The right IDE changes with the repo, so detection belongs next to
repo resolution and is resolved **once at session launch**, never re-sniffed.

| signal in the target repo | IDE |
|---|---|
| `Gemfile` | RubyMine |
| `pyproject.toml`, `setup.py`, or predominantly `.py` | PyCharm |
| `package.json` with no Gemfile | WebStorm |
| anything else, or several at once | IntelliJ IDEA (Ultimate handles all of them) |

Override with `FPS_IDE=rubymine` or `fps jet --ide pycharm`. Toolbox launchers are
already on PATH: `idea`, `pycharm`, `rubymine`, `webstorm`, `datagrip`, `goland`,
`clion`, `rider`, `dataspell`, `rustrover`, `studio`.

Worked examples: a Rails app → RubyMine. jobhunt, fps → PyCharm. `~/.claude` → IntelliJ.

## The constraint that has to be settled first

Generated run configurations live in **`.idea/runConfigurations/` inside the
target repo**. When that is a shared team repository, the standing rule is
that personal tooling never lands in something that ships to the team.

Options:

1. **`.git/info/exclude`** — a local-only ignore, not committed, invisible to
   everyone else. FPS appends `.idea/runConfigurations/fps-*.xml` on first run.
   Nothing enters the team's repo or its `.gitignore`. *Preferred.*
2. **A dedicated FPS project** at `~/.fps/projects/<slug>/` whose modules point at
   the real repo. Keeps the repo untouched, but loses the repo's own SDK, run
   configurations and VCS integration — which is most of why you would want the
   IDE.
3. **Ask the team to gitignore it.** Cheapest technically, but it puts personal
   tooling in a shared file. Ruled out.

Option 1, with the caveat that FPS must never write to a repo's tracked
`.gitignore`, and must be able to remove what it added.

## Multi-project windows

JetBrains' multi-root is **Attach** (`File → Open → <folder> → Attach`), and it is
a UI action with no CLI equivalent — there is no flag, and no persisted record in
the IDE configuration to write to. FPS cannot script it. If several repos need to
be open at once, that stays a manual three-click step, done once per window.

Not worth working around. The alternative — one synthetic project with modules
pointing at each repo — discards per-project SDKs and run configurations, which
costs more than it saves.

## Also available, lower priority

- **DataGrip data sources.** `.idea/dataSources.xml` can be generated for the FPS
  sqlite databases, so notices, open loops and the learning queue are browsable in
  the Database tool window instead of through the CLI. Composes directly with the
  per-repo database work — each targeted repo's database becomes a data source.
- **Global External Tools.** `fps-services notices`, `fps-learn add` bound to
  keystrokes, available in every project rather than per-repo.
- **Jump to line.** Notices that name a `file:line` can open there via
  `<launcher> --line N <path>`. `scripts/fps_vscode.py` already does editor work;
  it becomes `scripts/fps_jetbrains.py`.

## What is lost against iTerm

**Tab colour.** `fps-tab` sets per-role iTerm colours by escape code; run
configurations have names but no colour, and the JetBrains terminal does not read
those escape codes. Five identically-coloured tabs distinguished only by name.

Ordering and naming survive. If colour matters more than the MCP context, iTerm
stays the better host and this whole change is cosmetic — worth deciding
deliberately rather than discovering later.

## Proposed surface

```
fps jet              open the target repo in its IDE and start every role
fps jet forge        one role
fps jet --ide pycharm    override detection
fps jet --print      write nothing, print what would be generated
```

`fps code` is dropped. `fps mine` folds into `fps jet` and stays as an alias.
`fps` keeps opening iTerm tabs — this is an added host, not a replacement, and
the iTerm path is what works when the IDE is not running.

## Open questions

1. Does `fps jet` **replace** the iTerm default, or sit alongside it? Written
   above as alongside.
2. Should `fps jet` open the IDE if it is not already running, or only generate
   configurations and let it be opened by hand?
3. Colour versus MCP context — is the loss of coloured tabs acceptable?
4. Does the compound configuration start all five roles, or should warden and
   mentor be opt-in? Five sessions is a lot of tokens to start by reflex.

---

# Repo onboarding — tooling inventory

When a repo joins FPS, the bootstrap that learns the codebase should also learn
the **IDE** it will be worked in, and write down what is available. A repo that
joins without this gets an editor; a repo that joins with it gets a toolchain
someone has actually looked at.

This runs once, at join time, alongside the CLAUDE.md/architecture pass.

## What the pass does

1. **Resolve the IDE** for the repo, by the detection table above.
2. **Read that IDE's installed plugins** from
   `~/Library/Application Support/JetBrains/<IDE><version>/plugins`.
3. **Detect the repo's own signals** — `Gemfile`, `docker-compose*.yml`, `.env*`,
   test framework, linter configs, database config, whether it exposes an HTTP API.
4. **Cross the two.** A plugin only matters here if the repo has something for it
   to act on. Docker integration is noise in a repo with no compose file.
5. **Name the gaps** — capabilities the repo would benefit from where the plugin
   is *not* installed. "Get all the tools we could use" includes the ones missing.
6. **Write it into the repo**, as a file a human and a session both read.

## Inventory on this machine, 2026-08-28

Recorded because it is the input to step 4, and because it dates quickly.

| IDE | plugins | notable |
|---|---|---|
| RubyMine 2026.1.2 | 29 | `mcpserver`, `claude-code-jetbrains-plugin`, `Shell Script`, `restClient`, `clouds-docker-impl`, `dotenv`, `tasks`, `vcs-github-IU` |
| IntelliJ IDEA 2025.3.3 | 28 | `claude-code-jetbrains-plugin`, `restClient`, `terminal`, `tasks`, `toml`, docker, `jupyter-plugin` |
| PyCharm 2025.3.3 | 8 | `claude-code-jetbrains-plugin` |
| DataGrip 2025.3.5 | 1 | `mcpserver` |

Two cautions. PyCharm's plugin directory was **mid-migration** while this was
read — a settings backup is stamped the same evening — and the count moved
between reads. Any inventory step must tolerate that rather than record a
snapshot taken during an IDE update. And `mcpserver` appears as a discrete plugin
only in RubyMine and DataGrip; in the others the MCP server is bundled
differently. Detect the capability, not the plugin name.

## What each plugin actually unlocks

| plugin | what it gives a repo | applies when |
|---|---|---|
| `claude-code-jetbrains-plugin` | active file + selection as prompt context, native diff viewer, inspection diagnostics readable by the session | always — this is the reason to host FPS here |
| `mcpserver` | the IDE's own tools exposed to an MCP client | always |
| `Shell Script` | the run configurations that become role tabs | always — **required** for `fps jet` |
| `restClient` | `.http` files run in-IDE against the app | repo exposes an HTTP API |
| `clouds-docker-impl` | compose services started and inspected from the IDE | `docker-compose*.yml` present |
| `dotenv` | `.env` syntax, completion, no secrets in plain text | `.env*` present |
| `tasks` | issue tracker linked to branches and commits | repo has a tracker convention |
| `vcs-github-IU` | PR review inside the IDE | GitHub remote |
| Database tool window | FPS sqlite databases and the repo's dev database, browsable | always, for FPS's own state |

## What gets written into the repo

A single file — working name `docs/ide.md`, or wherever the repo keeps developer
docs — containing:

- **which IDE, and why** it was chosen for this repo
- **run configurations FPS generated**, and what each starts
- **how to run the test suite** from the IDE for this repo's framework
- **database tool window data sources**, both the repo's and the FPS databases
- **compose services**, if any, and how to start them from the IDE
- **linters and formatters**, and whether they are wired as inspections, File
  Watchers, or left to the CLI
- **the gap list** — useful plugins not installed, and what each would add

Written in the same register as the repo's other docs, not as a settings dump.
The test is whether a session reading it learns something it would otherwise have
to discover.

## Where it goes, and the same constraint

Identical to the run-configuration problem. In a **personal** repo the file is
committed like any other doc. In a **team** repo it describes one person's setup
and does not belong in shared history, so it lands under `.git/info/exclude`
alongside the generated run configurations.

Default to local-only and let promoting it to a committed doc be a deliberate
choice. FPS must never write to a tracked `.gitignore`, and must be able to
remove everything it added.

## Declaring required plugins

`.idea/externalDependencies.xml` lets a project declare plugins it needs, and the
IDE offers to install missing ones on open. That would turn the gap list into
something actionable rather than advisory.

**Unverified** — the file's schema has not been checked, and it is a *project*
file, so it carries the same team-repo constraint. Worth testing on a personal
repo before proposing it anywhere else.

## Open questions

5. Does the inventory pass run **only at join**, or refresh when the IDE updates?
   Plugin sets change; a doc that silently goes stale is worse than none.
6. Is `docs/ide.md` the right home, or should it live in the FPS per-repo store
   with only a pointer in the repo?
7. Does the gap list stay advisory, or does FPS offer to install what is missing?
