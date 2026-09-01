#!/usr/bin/env python3
"""Learn a repo well enough to write down how to work in it.

A new project joining FPS needs a page of facts nobody should have to rediscover:
what it is written in, how to run its tests, where things live, what it promises.
This reads those off the repo rather than asking for them.

It writes only what it observed. Anything it could not determine is left as an
explicit gap, because a confident wrong answer in a CLAUDE.md is worse than a
blank — every session downstream will act on it.

Repo-agnostic rules live in the global ~/.claude/CLAUDE.md and are not repeated
here; the file this writes holds only what is true of this one project.

Usage:
    fps_bootstrap.py [--repo PATH]           print the draft
    fps_bootstrap.py [--repo PATH] --write   write CLAUDE.md (never overwrites) + notes
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fps_tenant

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "vendor", "tmp", "log", ".idea"}
PROMISE_PATTERNS = (
    ("stdlib only", "stdlib only — no third-party imports"),
    ("no dependencies", "no dependencies"),
    ("zero dependencies", "no dependencies"),
    ("no install step", "no install step"),
    ("no build step", "no build step"),
)


def _read(path, limit=200_000):
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def _json(path):
    try:
        return json.loads(_read(path))
    except (json.JSONDecodeError, ValueError):
        return {}


# ------------------------------------------------------------------ detection

def detect_language(repo):
    """@return [Hash] {language, framework} — "unknown" rather than a guess."""
    repo = str(repo)
    def j(*p):
        return Path(repo).joinpath(*p)


    if j("Gemfile").is_file():
        gemfile = _read(j("Gemfile"))
        framework = "rails" if "rails" in gemfile and j("config").is_dir() else None
        return {"language": "ruby", "framework": framework}
    if j("package.json").is_file():
        pkg = _json(j("package.json"))
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        framework = next((f for f in ("next", "react", "vue", "svelte", "express") if f in deps), None)
        return {"language": "node", "framework": framework}
    if j("Package.swift").is_file() or any(n.endswith(".xcodeproj") for n in _listdir(repo)):
        return {"language": "swift", "framework": None}
    if j("go.mod").is_file():
        return {"language": "go", "framework": None}
    if _has_python(repo):
        return {"language": "python", "framework": None}
    return {"language": "unknown", "framework": None}


def _listdir(repo):
    try:
        return [c.name for c in Path(repo).iterdir()]
    except OSError:
        return []


def _has_python(repo):
    for name in _listdir(repo):
        if name.endswith(".py"):
            return True
        sub = Path(repo) / name
        if name not in SKIP_DIRS and sub.is_dir():
            try:
                if any(f.suffix == ".py" for f in sub.iterdir()):
                    return True
            except OSError:
                continue
    return False


def _python_commands(j, repo, _lang):
    out = {}
    if j("tests").is_dir():
        out["test"] = "python3 -m unittest discover -s tests"
    if j("pyproject.toml").is_file() and "ruff" in _read(j("pyproject.toml")):
        out["lint"] = "ruff check ."
    for pkg in (Path(repo).name, "src"):
        if j(pkg, "cli.py").is_file() and j(pkg, "__init__.py").is_file():
            out["run"] = f"python3 -m {pkg}.cli --help"
            break
    return out


def _ruby_commands(j, _repo, lang):
    out = {}
    if j("spec").is_dir():
        out["test"] = "bundle exec rspec"
    elif j("test").is_dir():
        out["test"] = "bundle exec rake test"
    if j(".rubocop.yml").is_file():
        out["lint"] = "bundle exec rubocop"
    if lang["framework"] == "rails":
        out["run"] = "bin/rails server"
    return out


def _node_commands(j, _repo, _lang):
    scripts = _json(j("package.json")).get("scripts", {})
    out = {}
    if "test" in scripts:
        out["test"] = "npm test"
    if "lint" in scripts:
        out["lint"] = "npm run lint"
    if "dev" in scripts:
        out["run"] = "npm run dev"
    elif "start" in scripts:
        out["run"] = "npm start"
    return out


def _swift_commands(j, _repo, _lang):
    if j("Package.swift").is_file():
        return {"test": "swift test", "run": "swift run"}
    return {}


def _go_commands(_j, _repo, _lang):
    return {"test": "go test ./...", "run": "go run ."}


COMMAND_DETECTORS = {
    "python": _python_commands, "ruby": _ruby_commands, "node": _node_commands,
    "swift": _swift_commands, "go": _go_commands,
}


def detect_commands(repo, lang):
    """@return [Hash] {test, lint, run} — None where nothing in the repo says."""
    repo = str(repo)

    def j(*p):
        return Path(repo).joinpath(*p)

    out = {"test": None, "lint": None, "run": None}
    detector = COMMAND_DETECTORS.get(lang["language"])
    if detector:
        out.update(detector(j, repo, lang))
    return out


def detect_layout(repo):
    """@return [Array<Hash>] top-level directories worth naming, with file counts."""
    repo = str(repo)
    entries = []
    for name in sorted(_listdir(repo)):
        if name.startswith(".") or name in SKIP_DIRS:
            continue
        path = Path(repo) / name
        if not Path(path).is_dir():
            continue
        count = 0
        for _, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            count += len(files)
        entries.append({"name": name, "files": count})
    return entries


def detect_promises(repo):
    """@return [Array<String>] promises the README makes that code could break."""
    repo = str(repo)
    for candidate in ("README.md", "readme.md", "README"):
        path = Path(repo) / candidate
        if Path(path).is_file():
            text = _read(path).lower()
            return sorted({label for needle, label in PROMISE_PATTERNS if needle in text})
    return []


def detect_git(repo):
    """@return [Hash] branch naming and commit style, read off recent history."""
    def git(*args):
        try:
            p = subprocess.run(["git", "-C", str(repo), *args], check=False,
                               capture_output=True, text=True, timeout=10)
            return p.stdout.strip() if p.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    default = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD").rpartition("/")[2]
    subjects = [s for s in git("log", "-30", "--format=%s").splitlines() if s]
    conventional = sum(1 for s in subjects if ":" in s.split(" ")[0]) if subjects else 0
    branches = [b.strip().lstrip("* ") for b in git("branch", "--format=%(refname:short)").splitlines()]
    return {
        "default_branch": default or None,
        "commit_style": "conventional (type: subject)" if subjects and conventional > len(subjects) / 2 else None,
        "recent_branches": [b for b in branches if b][:5],
    }


# -------------------------------------------------------------------- render

def learn(repo):
    """@return [Hash] everything observable about a repo, in one pass."""
    repo = str(repo)
    lang = detect_language(repo)
    return {
        "repo": repo,
        "name": Path(repo.rstrip("/")).name,
        "language": lang,
        "commands": detect_commands(repo, lang),
        "layout": detect_layout(repo),
        "promises": detect_promises(repo),
        "git": detect_git(repo),
        "learned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _stack_section(facts):
    lang = facts["language"]
    label = lang["language"] + (f" / {lang['framework']}" if lang["framework"] else "")
    return [f"# {facts['name']}", "",
            "Repo-specific facts. The working rules that apply everywhere live in",
            "`~/.claude/CLAUDE.md` and are not repeated here.", "",
            f"**Stack**: {label}", ""]


def _commands_section(cmds):
    out = ["## Commands", ""]
    if any(cmds.values()):
        out.append("```bash")
        for key, tag in (("test", "tests"), ("lint", "lint"), ("run", "run it")):
            if cmds[key]:
                out.append(f"{cmds[key]:<44}# {tag}")
        out.append("```")
    else:
        out += ["_Not determined from the repo._ Fill these in — a project whose test",
                "command nobody can name does not get its tests run."]
    if not cmds["test"]:
        out += ["", "**There is no test suite.** Nothing here is verified. Add one before",
                "changing behaviour, not after."]
    out.append("")
    return out


def _promises_section(facts):
    if not facts["promises"]:
        return []
    out = ["## Promises this repo makes", "",
           "The README states these. Breaking one silently makes the README false:", ""]
    out += [f"- {p}" for p in facts["promises"]]
    out += ["", "`~/.claude/skills/qa-gate/qa-gate.sh` enforces these where it can.", ""]
    return out


def _layout_section(facts):
    if not facts["layout"]:
        return []
    out = ["## Layout", "", "| Directory | Files |", "|---|---|"]
    out += [f"| `{d['name']}/` | {d['files']} |" for d in facts["layout"]]
    out.append("")
    return out


def _conventions_section(git):
    if not (git["default_branch"] or git["commit_style"]):
        return []
    out = ["## Conventions", ""]
    if git["default_branch"]:
        out.append(f"- Default branch: `{git['default_branch']}`")
    if git["commit_style"]:
        out.append(f"- Commit subjects: {git['commit_style']}")
    out.append("")
    return out


def _gaps_section(facts, cmds):
    out = ["## Gaps", ""]
    gaps = [name for name, value in
            (("test command", cmds["test"]), ("lint command", cmds["lint"]),
             ("run command", cmds["run"])) if not value]
    if gaps:
        out += ["Not determined by reading the repo — confirm before relying on any of it:", ""]
        out += [f"- {g}" for g in gaps]
    else:
        out.append("None — everything above was read off the repo.")
    out += ["", f"_Drafted by fps_bootstrap on {facts['learned_at'][:10]}. "
                "Edit freely; it will not overwrite you._", ""]
    return out


def render(facts):
    """@return [String] a CLAUDE.md draft containing only what was observed."""
    cmds = facts["commands"]
    return "\n".join(
        _stack_section(facts) + _commands_section(cmds) + _promises_section(facts)
        + _layout_section(facts) + _conventions_section(facts["git"])
        + _gaps_section(facts, cmds))


def write_out(repo, facts, write_repo_file=False):
    """Write the notes, and the repo's CLAUDE.md only when there is not one already.

    @return [Hash] {notes, claude_md} — paths written, or None where skipped
    """
    repo = str(repo)
    notes_dir = fps_tenant.home() / "notes" / fps_tenant.slug_for(repo)
    notes_dir.mkdir(parents=True, exist_ok=True)
    notes = notes_dir / "repo.md"
    body = render(facts)
    with notes.open("w") as fh:
        fh.write(body)

    written = None
    if write_repo_file:
        target = Path(repo) / "CLAUDE.md"
        # Never clobber a hand-written one: this draft is a starting point, and the
        # existing file is somebody's considered answer.
        if not Path(target).exists():
            with target.open("w") as fh:
                fh.write(body)
            written = target
    return {"notes": notes, "claude_md": written}


def main():
    ap = argparse.ArgumentParser(description="learn a repo and write down how to work in it")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--write", action="store_true",
                    help="write ~/.fps/notes/<slug>/repo.md and, if absent, the repo's CLAUDE.md")
    args = ap.parse_args()

    try:
        repo = fps_tenant.resolve_repo(args.repo)
    except fps_tenant.RepoBindingError as exc:
        print(f"fps: {exc}", file=sys.stderr)
        return 1

    facts = learn(repo)
    if not args.write:
        print(render(facts))
        return 0

    out = write_out(repo, facts, write_repo_file=True)
    print(f"notes:     {out['notes']}")
    print(f"CLAUDE.md: {out['claude_md'] or 'left alone — the repo already has one'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
