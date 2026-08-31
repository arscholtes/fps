#!/usr/bin/env python3
"""Local environment status, problems, and notices for the warden role.

Three jobs:
  status    what is running right now — containers, app processes, ports
  problems  what looks wrong, as a list, with nothing invented
  notices   messages left for the other sessions, delivered when they start

Deliberately read-only about services: it reports, it does not restart anything.
Something that silently restarts a server you were mid-debug on is worse than
something that tells you the server is down.

Usage:
    fps_services.py status
    fps_services.py problems [--quiet]
    fps_services.py sessions
    fps_services.py notify --what TEXT [--for ROLE] [--severity warn|error]
    fps_services.py notices [--all]
    fps_services.py ack ID
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fps_tenant

SESSION_DIR = os.path.expanduser("~/.claude/sessions")
# Ports the stack is expected to answer on. Override with FPS_PORTS="5432:postgres,..."
DEFAULT_PORTS = "5432:postgres,6379:redis,1025:smtp-sink,8025:mail-ui"
LOG_SCAN_BYTES = 200_000
ROLES = ("forge", "pilot", "shepherd", "warden", "mentor")


def run(cmd, timeout=15):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 1, ""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- services

def containers():
    if not shutil.which("docker"):
        return None
    code, out = run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"])
    if code != 0:
        return None
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if "\t" in line]


def worktree_from(cmd, repo_name):
    """The worktree a process belongs to, read out of its proctitle.

    A checkout named "<repo>-<branch>" is a worktree; the bare repo name is the
    main checkout and is not. The pattern is built from the bound repo's name
    rather than a literal, because a literal matches one repo and returns None
    for every other — and a None worktree is indistinguishable from a main
    checkout, so it fails silently.

    @param cmd [String] the process command line
    @param repo_name [String, nil] basename of the bound repo
    @return [String, nil] the worktree directory name, or None
    """
    if not repo_name:
        return None
    # A worktree is a DIRECTORY named <repo>-<branch>, so the match must be a
    # whole path segment. A bare prefix match reported "fps_services" as a
    # worktree of "fps" because underscore is a word character.
    #
    # Every match, not the first: worktrees sit beside the main checkout under a
    # parent named after the repo, so the first hit in /Developer/<repo>/<repo>-x
    # is the bare parent, which is not a worktree.
    pattern = rf"(?:^|[/\s]){re.escape(repo_name)}(?:-[\w.-]+)?(?=[/\s]|$)"
    for m in re.finditer(pattern, cmd):
        hit = m.group(0).lstrip("/ \t")
        if hit != repo_name:
            return hit
    return None


def app_processes(repo):
    """Puma/sidekiq/tailwind, with the worktree each belongs to where visible.

    @param repo [String] path of the bound repo, whose basename names its worktrees
    """
    repo_name = os.path.basename(os.path.realpath(repo)) if repo else ""
    code, out = run(["ps", "-Ao", "pid=,command="])
    if code != 0:
        return []
    found = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pid, _, cmd = line.partition(" ")
        low = cmd.lower()
        if "grep" in low:
            continue
        kind = None
        if low.startswith("puma") or " puma " in low:
            kind = "puma"
        elif "sidekiq" in low:
            kind = "sidekiq"
        elif "tailwindcss" in low:
            kind = "tailwind"
        if not kind:
            continue
        port = None
        m = re.search(r"tcp://[^:]+:(\d+)", cmd)
        if m:
            port = m.group(1)
        # Sidekiq puts its working directory in the proctitle; puma does not.
        wt = worktree_from(cmd, repo_name)
        found.append({"pid": pid, "kind": kind, "port": port, "worktree": wt})
    return found


def listening(port):
    code, _ = run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"])
    return code == 0


def expected_ports():
    spec = os.environ.get("FPS_PORTS", DEFAULT_PORTS)
    out = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        port, _, label = chunk.partition(":")
        out.append((port.strip(), label.strip() or port.strip()))
    return out


# --------------------------------------------------------------------------- sessions

def live_sessions():
    """Claude sessions currently running. Session files are not reaped, so a
    file only counts when its pid is still alive."""
    out = []
    for path in glob.glob(os.path.join(SESSION_DIR, "*.json")):
        try:
            d = json.load(open(path))
        except (OSError, json.JSONDecodeError):
            continue
        pid = d.get("pid")
        if not pid:
            continue
        try:
            os.kill(int(pid), 0)
        except (OSError, ValueError):
            continue
        out.append({
            "pid": pid,
            "name": d.get("name") or "(unnamed)",
            "cwd": d.get("cwd") or "",
            "kind": d.get("kind") or "",
        })
    return sorted(out, key=lambda s: s["name"])


# --------------------------------------------------------------------------- notices

def connect(repo):
    """@return [sqlite3.Connection] the tenant database for the bound repo."""
    return fps_tenant.connect_tenant(repo)


def cmd_notify(conn, args):
    if args.for_role and args.for_role not in ROLES:
        print(f"unknown role {args.for_role!r}; expected one of {', '.join(ROLES)}", file=sys.stderr)
        return 1
    conn.execute(
        "INSERT INTO notices (for_role, severity, body, created_at) VALUES (?, ?, ?, ?)",
        (args.for_role, args.severity, args.what, now()),
    )
    conn.commit()
    who = args.for_role or "everyone"
    print(f"notice queued for {who}: {args.what}")
    return 0


def _aged_out(created_at, ttl_days):
    """@return [Boolean] whether an unacked notice has outlived its delivery window."""
    try:
        then = datetime.fromisoformat(created_at)
    except (TypeError, ValueError):
        return False
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - then > timedelta(days=ttl_days)


def cmd_notices(conn, args):
    sql = "SELECT * FROM notices"
    params = []
    if not args.all:
        sql += " WHERE acked_at IS NULL"
        if args.for_role:
            sql += " AND (for_role IS NULL OR for_role = ?)"
            params.append(args.for_role)
    sql += " ORDER BY created_at ASC"
    rows = list(conn.execute(sql, params))

    stale = 0
    if not args.all:
        ttl = fps_tenant.notice_ttl_days()
        fresh = [r for r in rows if not _aged_out(r["created_at"], ttl)]
        stale = len(rows) - len(fresh)
        rows = fresh

    if not rows and not stale:
        if not args.quiet:
            print("no notices")
        return 0
    for r in rows:
        target = r["for_role"] or "all"
        state = "acked" if r["acked_at"] else r["severity"]
        print(f"  [{r['id']:>3}] {state:>5} -> {target:<9} {r['body']}")
    if stale and not args.quiet:
        print(f"\n  {stale} notice(s) aged out unacked past {fps_tenant.notice_ttl_days()}d — see --all.")
        print("  Ack a notice when you act on it; the queue is only read while it is short.")
    return 0


def cmd_ack(conn, args):
    cur = conn.execute("UPDATE notices SET acked_at = ? WHERE id = ? AND acked_at IS NULL", (now(), args.id))
    conn.commit()
    print(f"acked {args.id}" if cur.rowcount else f"no open notice with id {args.id}")
    return 0


# --------------------------------------------------------------------------- reports

def cmd_status(conn, args):
    print(f"local environment — {datetime.now().strftime('%a %b %d %H:%M')}")

    print("\ncontainers")
    cs = containers()
    if cs is None:
        print("  docker unavailable")
    elif not cs:
        print("  none running")
    else:
        for name, status in cs:
            print(f"  {name:<28} {status}")

    print("\nports")
    for port, label in expected_ports():
        print(f"  {port:<6} {label:<12} {'listening' if listening(port) else 'DOWN'}")

    print("\napp processes")
    procs = app_processes(args.repo_path)
    if not procs:
        print("  none")
    for p in procs:
        where = p["worktree"] or "-"
        port = f":{p['port']}" if p["port"] else ""
        print(f"  {p['kind']:<9} pid {p['pid']:<7} {port:<7} {where}")

    print("\nclaude sessions")
    for s in live_sessions():
        print(f"  {s['name'][:34]:<36} pid {s['pid']:<7} {os.path.basename(s['cwd'])}")
    return 0


def find_problems(repo):
    """Only things observed, never inferred. Each entry is (severity, text)."""
    problems = []

    cs = containers()
    if cs is not None:
        for name, status in cs:
            if "unhealthy" in status.lower() or "restarting" in status.lower():
                problems.append(("error", f"container {name} is {status}"))

    for port, label in expected_ports():
        if not listening(port):
            problems.append(("error", f"{label} is not listening on {port}"))

    procs = app_processes(repo)
    ports_seen = {}
    for p in procs:
        if p["port"]:
            ports_seen.setdefault(p["port"], []).append(p)
    for port, owners in ports_seen.items():
        if len(owners) > 1:
            pids = ", ".join(o["pid"] for o in owners)
            problems.append(("error", f"{len(owners)} processes claim port {port} (pids {pids})"))

    sidekiqs = [p for p in procs if p["kind"] == "sidekiq"]
    trees = {p["worktree"] for p in sidekiqs if p["worktree"]}
    if len(trees) > 1:
        problems.append(("warn", f"sidekiq running for {len(trees)} worktrees: {', '.join(sorted(trees))}"))

    log = os.path.join(repo, "log", "development.log")
    if os.path.exists(log):
        try:
            size = os.path.getsize(log)
            with open(log, "rb") as fh:
                fh.seek(max(0, size - LOG_SCAN_BYTES))
                tail = fh.read().decode("utf-8", "replace")
            fatals = re.findall(r"^.*(?:FATAL|Error during|undefined method|PG::\w+Error).*$", tail, re.M)
            if fatals:
                problems.append(("warn", f"{len(fatals)} error line(s) in the last {LOG_SCAN_BYTES // 1000}KB of development.log"))
        except OSError:
            pass

    return problems


def cmd_problems(conn, args):
    problems = find_problems(args.repo_path)
    if not problems:
        if not args.quiet:
            print("nothing looks wrong")
        return 0
    for sev, text in problems:
        print(f"  {sev:>5}  {text}")
    return 0


def cmd_sessions(conn, args):
    sessions = live_sessions()
    if not sessions:
        print("no live claude sessions")
        return 0
    for s in sessions:
        print(f"  {s['name'][:38]:<40} pid {s['pid']:<7} {s['cwd']}")
    return 0


def _repo_flag(parser, leading):
    """--repo reads naturally on either side of the subcommand, so accept both.

    Only the leading copy carries a default; the trailing one suppresses itself
    when absent, otherwise an omitted flag after the subcommand would overwrite
    the value given before it.
    """
    parser.add_argument("--repo", default=None if leading else argparse.SUPPRESS,
                        help="repo to act on; must match the session binding")


def build_parser():
    """@return [argparse.ArgumentParser] the fps-services command line."""
    ap = argparse.ArgumentParser()
    _repo_flag(ap, leading=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status")
    p_sessions = sub.add_parser("sessions")

    p_prob = sub.add_parser("problems")
    p_prob.add_argument("--quiet", action="store_true")

    p_not = sub.add_parser("notify")
    p_not.add_argument("--what", required=True)
    p_not.add_argument("--for", dest="for_role", default=None)
    p_not.add_argument("--severity", default="warn", choices=["warn", "error"])

    p_list = sub.add_parser("notices")
    p_list.add_argument("--all", action="store_true")
    p_list.add_argument("--quiet", action="store_true")
    p_list.add_argument("--for", dest="for_role", default=None)

    p_ack = sub.add_parser("ack")
    p_ack.add_argument("id", type=int)

    for p in (p_status, p_sessions, p_prob, p_not, p_list, p_ack):
        _repo_flag(p, leading=False)
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    try:
        args.repo_path = fps_tenant.resolve_repo(args.repo)
    except fps_tenant.RepoBindingError as exc:
        print(f"fps: {exc}", file=sys.stderr)
        return 1
    conn = connect(args.repo_path)
    return {
        "status": cmd_status, "problems": cmd_problems, "sessions": cmd_sessions,
        "notify": cmd_notify, "notices": cmd_notices, "ack": cmd_ack,
    }[args.cmd](conn, args)


if __name__ == "__main__":
    sys.exit(main())
