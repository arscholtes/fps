#!/usr/bin/env python3
"""Which repo an FPS session is bound to, and which database that repo owns.

FPS state splits along two different tenancies, and conflating them is what makes
a shared database wrong:

  repo-scoped    notices, open_loops — meaningless outside the project they name
  person-scoped  lessons, and the standup tables — they outlive any one employer

So only the repo-scoped tables shard. Lessons stay in the single global database
on purpose: the learning queue is the thing that survives changing jobs, and a
per-repo copy of it would defeat that. The standup tables stay for a harder
reason — a launchd job reads them from that exact path.

Binding is resolved once, at session launch, and never again. A session that
could follow its shell into another repo would silently write notices into the
wrong project's queue halfway through its own life, so a `--repo` that disagrees
with the launch binding is an error rather than a switch.

Usage:
    fps_tenant.py path [--repo PATH]     print the tenant database path
    fps_tenant.py join [--repo PATH]     create the tenant and register the repo
    fps_tenant.py list                   every repo that has joined
    fps_tenant.py migrate [--repo PATH]  copy repo-scoped rows out of the shared db
    fps_tenant.py which [--repo PATH]    the bound repo, its slug and database
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

# The person-scoped database. A launchd job (standup-morning-doc.sh) reads this
# path directly, so it is not ours to move.
GLOBAL_DB = "~/Desktop/weekly_standup/daily-standup-agent/standup.db"
DEFAULT_HOME = "~/.fps"
SLUG_HASH_LEN = 8
# Two weeks of session starts is every chance a notice will ever get to be read.
# Past that it is wallpaper, and wallpaper is what stopped the queue being read
# in the first place. Aged-out notices are hidden, never deleted.
DEFAULT_NOTICE_TTL_DAYS = 14


class RepoBindingError(Exception):
    """The repo could not be resolved, or resolving it would change the binding."""


# --------------------------------------------------------------------------- paths

def home():
    """@return [String] the FPS state directory, outside every target repo."""
    return os.path.expanduser(os.environ.get("FPS_HOME", DEFAULT_HOME))


def registry_path():
    return os.path.join(home(), "repos.json")


def global_db_path():
    return os.path.expanduser(os.environ.get("FPS_GLOBAL_DB", GLOBAL_DB))


def slug_for(repo):
    """Filesystem-safe identity for a repo path.

    The basename makes the file recognisable by eye; the path hash keeps two
    checkouts with the same basename apart. Symlinks and `.` segments normalise
    first so one repo can never end up owning two tenants.

    @param repo [String] path to the repo
    @return [String] e.g. "workrepo-3f2a9c1b"
    """
    real = os.path.realpath(os.path.expanduser(repo))
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(real)).strip("-") or "repo"
    digest = hashlib.sha256(real.encode("utf-8")).hexdigest()[:SLUG_HASH_LEN]
    return f"{base}-{digest}"


def config_path_for(repo):
    """@return [String] optional per-repo settings, kept outside the repo itself."""
    return os.path.join(home(), "config", f"{slug_for(repo)}.json")


def config_for(repo):
    """Per-repo overrides (pilot_dir, ports, blurb). Absent or unreadable means none.

    @param repo [String] path to the repo
    @return [Hash]
    """
    try:
        with open(config_path_for(repo)) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def db_path_for(repo):
    """@return [String] the tenant database for a repo, under FPS home."""
    return os.path.join(home(), "dbs", f"{slug_for(repo)}.db")


# --------------------------------------------------------------------------- binding

def resolve_repo(explicit=None):
    """Resolve the repo this invocation acts on, honouring the session binding.

    @param explicit [String, nil] a --repo argument, if one was given
    @raise [RepoBindingError] if the directory is missing, or if an explicit repo
      disagrees with the repo this session was bound to at launch
    @return [String] the real path of the bound repo
    """
    bound = os.environ.get("FPS_BOUND_REPO") or ""
    bound = os.path.realpath(os.path.expanduser(bound)) if bound else ""

    if explicit:
        chosen = os.path.realpath(os.path.expanduser(explicit))
        if bound and chosen != bound:
            raise RepoBindingError(
                f"this session is bound to {bound}; it cannot act on {chosen}.\n"
                "Repo binding is fixed for the life of a session — start a new one for another repo."
            )
    elif bound:
        chosen = bound
    else:
        chosen = os.path.realpath(os.path.expanduser(
            os.environ.get("FPS_REPO") or os.getcwd()))

    if not os.path.isdir(chosen):
        raise RepoBindingError(f"no such directory: {chosen}")
    return chosen


# --------------------------------------------------------------------------- registry

def list_repos():
    """@return [Array<Hash>] every joined repo, oldest first; empty if unreadable."""
    try:
        with open(registry_path()) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    entries = [dict(v, slug=k) for k, v in data.items() if isinstance(v, dict)]
    return sorted(entries, key=lambda e: e.get("joined_at") or "")


def join(repo):
    """Register a repo and make sure its tenant database exists.

    @param repo [String] path to the repo
    @return [String] the tenant database path
    """
    real = os.path.realpath(os.path.expanduser(repo))
    os.makedirs(os.path.join(home(), "dbs"), exist_ok=True)

    try:
        with open(registry_path()) as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError, ValueError):
        data = {}

    slug = slug_for(real)
    if slug not in data:
        data[slug] = {"path": real, "joined_at": _now()}
        tmp = registry_path() + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, registry_path())
    return db_path_for(real)


# --------------------------------------------------------------------------- tenant db

TENANT_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS notices (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           for_role TEXT,
           severity TEXT NOT NULL DEFAULT 'warn',
           body TEXT NOT NULL,
           created_at TEXT NOT NULL,
           acked_at TEXT
       )""",
    """CREATE TABLE IF NOT EXISTS open_loops (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           asked_of TEXT NOT NULL,
           question TEXT NOT NULL,
           where_url TEXT,
           asked_at TEXT NOT NULL,
           resolved_at TEXT
       )""",
)


def connect_tenant(repo):
    """Open (creating on first use) the repo-scoped database.

    @param repo [String] path to the repo
    @return [sqlite3.Connection] with row_factory set and the schema applied
    """
    db = join(repo)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    for stmt in TENANT_SCHEMA:
        conn.execute(stmt)
    conn.commit()
    return conn


def connect_global():
    """@return [sqlite3.Connection] the person-scoped database (lessons, standup)."""
    conn = sqlite3.connect(global_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def notice_ttl_days():
    """@return [Integer] days an unacked notice stays visible before ageing out."""
    raw = os.environ.get("FPS_NOTICE_TTL_DAYS")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_NOTICE_TTL_DAYS
    return value if value > 0 else DEFAULT_NOTICE_TTL_DAYS


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def migrate_from_global(repo):
    """Copy the repo-scoped rows out of the shared database into a repo's tenant.

    Rows are matched on their content so a second run is a no-op, and the global
    copies are left in place — they simply stop being read once every script
    resolves through the tenant. Person-scoped tables are never touched.

    @param repo [String] path to the repo the rows belong to
    @return [Hash] {table => rows copied}
    """
    src_path = global_db_path()
    if not os.path.exists(src_path):
        return {"notices": 0, "open_loops": 0}

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    dest = connect_tenant(repo)
    copied = {}

    columns = {
        "notices": ("for_role", "severity", "body", "created_at", "acked_at"),
        "open_loops": ("asked_of", "question", "where_url", "asked_at", "resolved_at"),
    }
    identity = {"notices": ("body", "created_at"), "open_loops": ("question", "asked_at")}

    for table, cols in columns.items():
        try:
            rows = list(src.execute(f"SELECT {', '.join(cols)} FROM {table}"))
        except sqlite3.OperationalError:
            copied[table] = 0
            continue
        key_a, key_b = identity[table]
        seen = {tuple(r) for r in dest.execute(f"SELECT {key_a}, {key_b} FROM {table}")}
        n = 0
        for row in rows:
            if (row[key_a], row[key_b]) in seen:
                continue
            dest.execute(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                tuple(row[c] for c in cols))
            seen.add((row[key_a], row[key_b]))
            n += 1
        copied[table] = n

    dest.commit()
    dest.close()
    src.close()
    return copied


# --------------------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description="FPS repo binding and tenant databases")
    ap.add_argument("--repo", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("path", "join", "which", "migrate", "config"):
        sub.add_parser(name)
    sub.add_parser("list")

    args = ap.parse_args()

    if args.cmd == "list":
        entries = list_repos()
        if not entries:
            print("no repos have joined FPS yet")
            return 0
        for e in entries:
            print(f"  {e['slug']:<28} {e['path']}")
        return 0

    try:
        repo = resolve_repo(args.repo)
    except RepoBindingError as exc:
        print(f"fps: {exc}", file=sys.stderr)
        return 1

    if args.cmd == "path":
        print(db_path_for(repo))
    elif args.cmd == "join":
        print(f"joined: {repo}\n  tenant: {join(repo)}")
    elif args.cmd == "migrate":
        counts = migrate_from_global(repo)
        print(f"migrated into {db_path_for(repo)}")
        for table, n in sorted(counts.items()):
            print(f"  {table:<12} {n} row(s) copied")
        print("  the shared database keeps its copies; nothing reads them now.")
    elif args.cmd == "config":
        cfg = config_for(repo)
        print(json.dumps(cfg, indent=2, sort_keys=True) if cfg else "{}")
    elif args.cmd == "which":
        bound = "bound" if os.environ.get("FPS_BOUND_REPO") else "unbound (resolved from cwd)"
        print(f"  repo   {repo}  [{bound}]")
        print(f"  slug   {slug_for(repo)}")
        print(f"  db     {db_path_for(repo)}")
        print(f"  global {global_db_path()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
