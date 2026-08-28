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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fps_tenant  # noqa: E402

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
        with open(path, encoding="utf-8", errors="replace") as fh:
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
    j = lambda *p: os.path.join(repo, *p)  # noqa: E731

    if os.path.isfile(j("Gemfile")):
        gemfile = _read(j("Gemfile"))
        framework = "rails" if "rails" in gemfile and os.path.isdir(j("config")) else None
        return {"language": "ruby", "framework": framework}
    if os.path.isfile(j("package.json")):
        pkg = _json(j("package.json"))
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        framework = next((f for f in ("next", "react", "vue", "svelte", "express") if f in deps), None)
        return {"language": "node", "framework": framework}
    if os.path.isfile(j("Package.swift")) or any(n.endswith(".xcodeproj") for n in _listdir(repo)):
        return {"language": "swift", "framework": None}
    if os.path.isfile(j("go.mod")):
        return {"language": "go", "framework": None}
    if _has_python(repo):
        return {"language": "python", "framework": None}
    return {"language": "unknown", "framework": None}


def _listdir(repo):
    try:
        return os.listdir(repo)
    except OSError:
        return []


def _has_python(repo):
    for name in _listdir(repo):
        if name.endswith(".py"):
            return True
        sub = os.path.join(repo, name)
        if name not in SKIP_DIRS and os.path.isdir(sub):
            try:
                if any(f.endswith(".py") for f in os.listdir(sub)):
                    return True
            except OSError:
                continue
    return False


def detect_commands(repo, lang):
    """@return [Hash] {test, lint, run} — None where nothing in the repo says."""
    repo = str(repo)
    j = lambda *p: os.path.join(repo, *p)  # noqa: E731
    out = {"test": None, "lint": None, "run": None}
    language = lang["language"]

    if language == "python":
        if os.path.isdir(j("tests")):
            out["test"] = "python3 -m unittest discover -s tests"
        if os.path.isfile(j("pyproject.toml")) and "ruff" in _read(j("pyproject.toml")):
            out["lint"] = "ruff check ."
        for pkg in (os.path.basename(repo), "src"):
            if os.path.isfile(j(pkg, "cli.py")) and os.path.isfile(j(pkg, "__init__.py")):
                out["run"] = f"python3 -m {pkg}.cli --help"
                break
    elif language == "ruby":
        if os.path.isdir(j("spec")):
            out["test"] = "bundle exec rspec"
        elif os.path.isdir(j("test")):
            out["test"] = "bundle exec rake test"
        if os.path.isfile(j(".rubocop.yml")):
            out["lint"] = "bundle exec rubocop"
        if lang["framework"] == "rails":
            out["run"] = "bin/rails server"
    elif language == "node":
        scripts = _json(j("package.json")).get("scripts", {})
        if "test" in scripts:
            out["test"] = "npm test"
        if "lint" in scripts:
            out["lint"] = "npm run lint"
        if "dev" in scripts:
            out["run"] = "npm run dev"
        elif "start" in scripts:
            out["run"] = "npm start"
    elif language == "swift":
        if os.path.isfile(j("Package.swift")):
            out["test"] = "swift test"
            out["run"] = "swift run"
    elif language == "go":
        out["test"] = "go test ./..."
        out["run"] = "go run ."
    return out


def detect_layout(repo):
    """@return [Array<Hash>] top-level directories worth naming, with file counts."""
    repo = str(repo)
    entries = []
    for name in sorted(_listdir(repo)):
        if name.startswith(".") or name in SKIP_DIRS:
            continue
        path = os.path.join(repo, name)
        if not os.path.isdir(path):
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
        path = os.path.join(repo, candidate)
        if os.path.isfile(path):
            text = _read(path).lower()
            return sorted({label for needle, label in PROMISE_PATTERNS if needle in text})
    return []


def detect_git(repo):
    """@return [Hash] branch naming and commit style, read off recent history."""
    def git(*args):
        try:
            p = subprocess.run(["git", "-C", str(repo), *args],
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
        "name": os.path.basename(repo.rstrip("/")),
        "language": lang,
        "commands": detect_commands(repo, lang),
        "layout": detect_layout(repo),
        "promises": detect_promises(repo),
        "git": detect_git(repo),
        "learned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def render(facts):
    """@return [String] a CLAUDE.md draft containing only what was observed."""
    L = []
    lang = facts["language"]
    label = lang["language"] + (f" / {lang['framework']}" if lang["framework"] else "")

    L.append(f"# {facts['name']}")
    L.append("")
    L.append("Repo-specific facts. The working rules that apply everywhere live in")
    L.append("`~/.claude/CLAUDE.md` and are not repeated here.")
    L.append("")
    L.append(f"**Stack**: {label}")
    L.append("")

    cmds = facts["commands"]
    L.append("## Commands")
    L.append("")
    if any(cmds.values()):
        L.append("```bash")
        for key, tag in (("test", "tests"), ("lint", "lint"), ("run", "run it")):
            if cmds[key]:
                L.append(f"{cmds[key]:<44}# {tag}")
        L.append("```")
    else:
        L.append("_Not determined from the repo._ Fill these in — a project whose test")
        L.append("command nobody can name does not get its tests run.")
    if not cmds["test"]:
        L.append("")
        L.append("**There is no test suite.** Nothing here is verified. Add one before")
        L.append("changing behaviour, not after.")
    L.append("")

    if facts["promises"]:
        L.append("## Promises this repo makes")
        L.append("")
        L.append("The README states these. Breaking one silently makes the README false:")
        L.append("")
        for p in facts["promises"]:
            L.append(f"- {p}")
        L.append("")
        L.append("`~/.claude/skills/qa-gate/qa-gate.sh` enforces these where it can.")
        L.append("")

    if facts["layout"]:
        L.append("## Layout")
        L.append("")
        L.append("| Directory | Files |")
        L.append("|---|---|")
        for d in facts["layout"]:
            L.append(f"| `{d['name']}/` | {d['files']} |")
        L.append("")

    git = facts["git"]
    if git["default_branch"] or git["commit_style"]:
        L.append("## Conventions")
        L.append("")
        if git["default_branch"]:
            L.append(f"- Default branch: `{git['default_branch']}`")
        if git["commit_style"]:
            L.append(f"- Commit subjects: {git['commit_style']}")
        L.append("")

    L.append("## Gaps")
    L.append("")
    gaps = [name for name, value in
            (("test command", cmds["test"]), ("lint command", cmds["lint"]),
             ("run command", cmds["run"])) if not value]
    if gaps:
        L.append("Not determined by reading the repo — confirm before relying on any of it:")
        L.append("")
        for g in gaps:
            L.append(f"- {g}")
    else:
        L.append("None — everything above was read off the repo.")
    L.append("")
    L.append(f"_Drafted by fps_bootstrap on {facts['learned_at'][:10]}. Edit freely; it will not overwrite you._")
    L.append("")
    return "\n".join(L)


def write_out(repo, facts, write_repo_file=False):
    """Write the notes, and the repo's CLAUDE.md only when there is not one already.

    @return [Hash] {notes, claude_md} — paths written, or None where skipped
    """
    repo = str(repo)
    notes_dir = os.path.join(fps_tenant.home(), "notes", fps_tenant.slug_for(repo))
    os.makedirs(notes_dir, exist_ok=True)
    notes = os.path.join(notes_dir, "repo.md")
    body = render(facts)
    with open(notes, "w") as fh:
        fh.write(body)

    written = None
    if write_repo_file:
        target = os.path.join(repo, "CLAUDE.md")
        # Never clobber a hand-written one: this draft is a starting point, and the
        # existing file is somebody's considered answer.
        if not os.path.exists(target):
            with open(target, "w") as fh:
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
