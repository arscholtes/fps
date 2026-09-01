#!/usr/bin/env python3
"""Generate an FPS workspace for VS Code and open it.

VS Code cannot colour a terminal from an escape code the way iTerm can, so each
role becomes a terminal *profile* carrying its own colour and icon. The workspace
file lives outside the repository, so nothing is added to the project.

Roles arrive two ways, because each covers the other's gap. Tasks open every role
automatically when the workspace opens, and carry a coloured icon. Profiles sit in
the terminal dropdown for opening one by hand later.

Automatic tasks need workspace trust: the first open asks whether to allow them,
and answering no leaves the profiles working.

Usage:
    fps_vscode.py [--repo PATH] [--print]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# VS Code accepts theme colour ids, not RGB, so these are the nearest ansi
# equivalents of the iTerm tab colours.
ROLES = [
    ("forge",    "terminal.ansiGreen",   "tools"),
    ("pilot",    "terminal.ansiBlue",    "compass"),
    ("shepherd", "terminal.ansiRed",     "git-pull-request"),
    ("warden",   "terminal.ansiMagenta", "pulse"),
    ("mentor",   "terminal.ansiCyan",    "mortar-board"),
    ("shell",    None,                   "terminal"),
]

WORKSPACE = Path("~/.fps/fps.code-workspace").expanduser()


def build(repo):
    profiles = {}
    for role, colour, icon in ROLES:
        cmd = f"fps {role} --here" if role != "shell" else "cd " + repo
        profile = {
            "path": os.environ.get("SHELL", "/bin/zsh"),
            "args": ["-l"] if role == "shell" else ["-lc", cmd],
            "icon": icon,
        }
        if colour:
            profile["color"] = colour
        profiles[role] = profile

    tasks = []
    for role, colour, icon in ROLES:
        cmd = f"fps {role} --here" if role != "shell" else f"cd {repo}"
        task = {
            "label": role,
            "type": "shell",
            "command": cmd,
            "isBackground": True,
            "presentation": {
                # A dedicated panel per task is what makes these separate tabs
                # rather than one terminal reused six times.
                "panel": "dedicated",
                "group": "fps",
                "reveal": "always",
                "showReuseMessage": False,
                "clear": False,
            },
            "runOptions": {"runOn": "folderOpen"},
            "problemMatcher": [],
        }
        task["icon"] = {"id": icon} if not colour else {"id": icon, "color": colour}
        tasks.append(task)

    return {
        "folders": [{"path": repo}],
        "settings": {
            "terminal.integrated.profiles.osx": profiles,
            "terminal.integrated.tabs.enabled": True,
            "terminal.integrated.tabs.location": "left",
        },
        "tasks": {"version": "2.0.0", "tasks": tasks},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--print", action="store_true", help="write nothing, just show it")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fps_tenant

    try:
        args.repo = fps_tenant.resolve_repo(args.repo)
    except fps_tenant.RepoBindingError as exc:
        print(f"fps: {exc}", file=sys.stderr)
        return 1

    ws = build(args.repo)
    if args.print:
        print(json.dumps(ws, indent=2))
        return 0

    WORKSPACE.parent.mkdir(parents=True, exist_ok=True)
    with WORKSPACE.open("w") as fh:
        json.dump(ws, fh, indent=2)
        fh.write("\n")

    code = shutil_which("code")
    if not code:
        print(f"workspace written: {WORKSPACE}")
        print("`code` is not on PATH — open that file from VS Code yourself.")
        return 0

    subprocess.run([code, "-n", WORKSPACE])
    print(f"opened {WORKSPACE.name} in VS Code")
    print("Allow automatic tasks when asked — that is what opens the role terminals.")
    print("The terminal dropdown also has one profile per role, for opening one by hand.")
    return 0


def shutil_which(name):
    from shutil import which
    return which(name)


if __name__ == "__main__":
    sys.exit(main())
