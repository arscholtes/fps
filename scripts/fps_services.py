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
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fps_tenant

SESSION_DIR = Path("~/.claude/sessions").expanduser()
# Ports the stack is expected to answer on. Override with FPS_PORTS="5432:postgres,..."
DEFAULT_PORTS = "5432:postgres,6379:redis,1025:smtp-sink,8025:mail-ui"
LOG_SCAN_BYTES = 200_000
ROLES = ("forge", "pilot", "shepherd", "warden", "mentor")


def run(cmd, timeout=15):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
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
    repo_name = Path(repo).resolve().name if repo else ""
    code, out = run(["ps", "-Ao", "pid=,command="])
    if code != 0:
        return []
    found = []
    for raw_line in out.splitlines():
        line = raw_line.strip()
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
    for raw_chunk in spec.split(","):
        chunk = raw_chunk.strip()
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
    for path in sorted(SESSION_DIR.glob("*.json")):
        try:
            with path.open() as fh:
                d = json.load(fh)
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


# Hermes runs the same roles under a different agent. It keeps sessions in its own
# per-profile SQLite store, but liveness is asked of the process rather than that
# store, for the same reason it is for Claude: a record outlives the thing it
# describes, and a pid that answers does not.
HERMES_PROFILE = re.compile(r"(?:^|\s)(?:-p|--profile)[\s=]+(\w+)")


def hermes_profile(cmdline):
    """The profile a hermes command line names.

    @param cmdline [String] a full process command line
    @return [String, nil] profile name, or nil when this is not a hermes session
    """
    if "/hermes" not in cmdline and not cmdline.startswith("hermes"):
        return None
    match = HERMES_PROFILE.search(cmdline)
    return match.group(1) if match else None


def hermes_sessions():
    """Running hermes sessions, discovered by process rather than by its store."""
    try:
        listing = subprocess.run(["ps", "-axo", "pid=,command="], check=False,
                                 capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in listing.splitlines():
        pid, _, cmdline = line.strip().partition(" ")
        profile = hermes_profile(cmdline)
        if not profile or not pid.isdigit():
            continue
        out.append({"pid": int(pid), "name": profile, "cwd": _cwd_of(int(pid)), "kind": "hermes"})
    return sorted(out, key=lambda s: s["name"])


def _cwd_of(pid):
    """@return [String] the process working directory, or "" when it cannot be read."""
    try:
        result = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                                check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            return line[1:]
    return ""


# --------------------------------------------------------------------------- notices

def connect(repo):
    """@return [sqlite3.Connection] the tenant database for the bound repo."""
    return fps_tenant.connect_tenant(repo)


# A notice carries a fact; a spec goes in a bead. The charter has said so since it
# was written and it was ignored anyway: of the first 45 notices sent, the median
# body ran 1,351 characters and two were under 400. On 2026-09-06 twelve of the
# fifteen unacked in forge's queue were specs, three of them asking for the same
# build on three separate days, none of which ever became a bead.
#
# The cap is 400 because the two shortest real notices ever sent were 296 and 358.
# It is a refusal rather than a warning because the rule already existed as advice
# and that is precisely what did not work.
NOTICE_MAX_CHARS = 400


def too_long_to_be_a_fact(body):
    """@return [String, nil] why this body cannot be a notice, or nil if it can."""
    length = len(body or "")
    if length <= NOTICE_MAX_CHARS:
        return None
    return (f"this is {length} characters; a notice caps at {NOTICE_MAX_CHARS}.\n"
            "     A notice carries a fact — what broke, what it blocks. Anything longer\n"
            "     is a spec, and a spec goes in a bead where it can be sequenced,\n"
            "     depended on and closed:\n"
            "       bd create \"<title>\" -p 2 -d \"<the spec>\"\n"
            "     Then send the notice as one line pointing at the bead id.")


def cmd_notify(conn, args):
    if args.for_role and args.for_role not in ROLES:
        print(f"unknown role {args.for_role!r}; expected one of {', '.join(ROLES)}", file=sys.stderr)
        return 1
    problem = too_long_to_be_a_fact(args.what)
    if problem:
        print(f"fps-services notify: {problem}", file=sys.stderr)
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


def _unacked_rows(repo, for_role):
    """@return [Array<sqlite3.Row>] unacked notices for a role in another tenant."""
    try:
        conn = fps_tenant.connect_tenant(repo)
        sql = "SELECT * FROM notices WHERE acked_at IS NULL"
        params = []
        if for_role:
            sql += " AND (for_role IS NULL OR for_role = ?)"
            params.append(for_role)
        return list(conn.execute(sql + " ORDER BY created_at ASC", params))
    except Exception:
        return []


def _elsewhere(repo, for_role):
    """Unacked notices in every joined repo except this one.

    A notice is addressed to a role, and the role is the same person in every
    repo. Scoping the empty case to one tenant hid a pending-work batch and
    a P1 behind a message saying there were none. Read-only; the session binding
    still governs every write.

    @return [Array<(String, Array<sqlite3.Row>)>] repo name and its notices.
    """
    here = str(Path(repo).resolve()) if repo else None
    found = []
    for entry in fps_tenant.list_repos():
        path = entry.get("path")
        if not path or (here and str(Path(path).resolve()) == here):
            continue
        rows = _unacked_rows(path, for_role)
        if rows:
            found.append((Path(path).name, rows))
    return found


def cmd_notices(conn, args, repo=None):
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
            where = Path(repo).name if repo else "this repo"
            print(f"no notices in {where}")
            for name, found in _elsewhere(repo, args.for_role):
                print(f"\n  {len(found)} unread in {name}:")
                for r in found:
                    print(f"    [{r['id']}] {(r['created_at'] or '')[:10]}  {r['body']}")
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

def cmd_status(_conn, args):
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
        print(f"  {s['name'][:34]:<36} pid {s['pid']:<7} {Path(s['cwd']).name}")
    return 0


def _container_problems():
    cs = containers()
    if cs is None:
        return []
    return [("error", f"container {name} is {status}") for name, status in cs
            if "unhealthy" in status.lower() or "restarting" in status.lower()]


def _port_problems():
    return [("error", f"{label} is not listening on {port}")
            for port, label in expected_ports() if not listening(port)]


def _port_conflict_problems(procs):
    ports_seen = {}
    for proc in procs:
        if proc["port"]:
            ports_seen.setdefault(proc["port"], []).append(proc)
    out = []
    for port, owners in ports_seen.items():
        if len(owners) > 1:
            pids = ", ".join(o["pid"] for o in owners)
            out.append(("error", f"{len(owners)} processes claim port {port} (pids {pids})"))
    return out


def _sidekiq_problems(procs):
    trees = {p["worktree"] for p in procs if p["kind"] == "sidekiq" and p["worktree"]}
    if len(trees) > 1:
        return [("warn", f"sidekiq running for {len(trees)} worktrees: {', '.join(sorted(trees))}")]
    return []


def _log_problems(repo):
    """Error lines in the tail of development.log. An unreadable log is not a problem."""
    log = Path(repo) / "log" / "development.log"
    if not log.exists():
        return []
    try:
        size = log.stat().st_size
        with log.open("rb") as fh:
            fh.seek(max(0, size - LOG_SCAN_BYTES))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    fatals = re.findall(r"^.*(?:FATAL|Error during|undefined method|PG::\w+Error).*$", tail, re.M)
    if fatals:
        return [("warn", f"{len(fatals)} error line(s) in the last "
                         f"{LOG_SCAN_BYTES // 1000}KB of development.log")]
    return []


def find_problems(repo):
    """Only things observed, never inferred. Each entry is (severity, text)."""
    procs = app_processes(repo)
    return (_container_problems() + _port_problems()
            + _port_conflict_problems(procs) + _sidekiq_problems(procs)
            + _log_problems(repo))


def cmd_problems(_conn, args):
    problems = find_problems(args.repo_path)
    if not problems:
        if not args.quiet:
            print("nothing looks wrong")
        return 0
    for sev, text in problems:
        print(f"  {sev:>5}  {text}")
    return 0


def cmd_sessions(_conn, _args):
    sessions = live_sessions() + hermes_sessions()
    if not sessions:
        print("no live sessions")
        return 0
    # The agent is named only when more than one is in play. A single-agent machine
    # does not need a column telling it so.
    mixed = len({s.get("kind") == "hermes" for s in sessions}) > 1
    for s in sorted(sessions, key=lambda x: (x["name"], x["pid"])):
        agent = "  [hermes]" if mixed and s.get("kind") == "hermes" else ""
        print(f"  {s['name'][:38]:<40} pid {s['pid']:<7} {s['cwd']}{agent}")
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
        "notify": cmd_notify,
        "notices": lambda c, a: cmd_notices(c, a, args.repo_path),
        "ack": cmd_ack,
    }[args.cmd](conn, args)


if __name__ == "__main__":
    sys.exit(main())
