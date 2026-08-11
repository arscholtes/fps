#!/usr/bin/env python3
"""Open-loop tracking for the FPS system.

An open loop is a question asked of a person that never came back. Nothing else in
the stack tracks these: the issue tracker holds work, git holds code, the calendar
holds time. A question asked in a comment thread is held by nobody, so it rots.

Deliberately one table. Cross-session coordination is handled by Claude Code's own
session messaging, not here — a shared-state file that grows becomes archaeology,
and every reported multi-agent setup that added one regretted it.

Usage:
    fps_state.py init
    fps_state.py add --who NAME --what TEXT [--where URL]
    fps_state.py list [--all]
    fps_state.py close ID
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

DEFAULT_DB = os.path.expanduser("~/Desktop/weekly_standup/daily-standup-agent/standup.db")
STALE_DAYS = 3
# Past this, the list stops being read at all. Yegge's calibrated ceiling for an
# agent-queryable working set is ~200 items; an open-loop list should never be close.
WARN_COUNT = 25


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS open_loops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asked_of TEXT NOT NULL,
            question TEXT NOT NULL,
            where_url TEXT,
            asked_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """
    )
    conn.commit()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def age_days(iso):
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return 0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).days


def cmd_add(conn, args):
    # Loops are usually recorded after the fact, so the age is only honest if the
    # original date can be supplied.
    asked_at = args.asked_at or now()
    conn.execute(
        "INSERT INTO open_loops (asked_of, question, where_url, asked_at) VALUES (?, ?, ?, ?)",
        (args.who, args.what, args.where, asked_at),
    )
    conn.commit()
    print(f"tracked ({age_days(asked_at)}d): asked {args.who} — {args.what}")


def cmd_list(conn, args):
    sql = "SELECT * FROM open_loops"
    if not args.all:
        sql += " WHERE resolved_at IS NULL"
    sql += " ORDER BY asked_at ASC"
    rows = list(conn.execute(sql))
    if not rows:
        print("no open loops")
        return
    for r in rows:
        days = age_days(r["asked_at"])
        flag = "  <-- stale" if days >= STALE_DAYS and not r["resolved_at"] else ""
        state = "closed" if r["resolved_at"] else f"{days}d"
        print(f"  [{r['id']:>3}] {state:>6}  {r['asked_of']}: {r['question']}{flag}")
        if r["where_url"]:
            print(f"        {r['where_url']}")
    open_count = sum(1 for r in rows if not r["resolved_at"])
    if open_count > WARN_COUNT:
        print(f"\n  {open_count} open loops — past this many the list stops getting read.")
        print("  Close what is actually dead rather than letting it grow.")


def cmd_close(conn, args):
    cur = conn.execute(
        "UPDATE open_loops SET resolved_at = ? WHERE id = ? AND resolved_at IS NULL",
        (now(), args.id),
    )
    conn.commit()
    print(f"closed {args.id}" if cur.rowcount else f"no open loop with id {args.id}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("FPS_DB", DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init")

    p_add = sub.add_parser("add")
    p_add.add_argument("--who", required=True)
    p_add.add_argument("--what", required=True)
    p_add.add_argument("--where", default=None)
    p_add.add_argument("--asked-at", dest="asked_at", default=None,
                       help="ISO date the question was actually asked (default: now)")

    p_list = sub.add_parser("list")
    p_list.add_argument("--all", action="store_true")

    p_close = sub.add_parser("close")
    p_close.add_argument("id", type=int)

    args = ap.parse_args()

    if not os.path.exists(os.path.dirname(args.db)):
        print(f"no such directory for db: {args.db}", file=sys.stderr)
        return 1

    conn = connect(args.db)
    init(conn)
    {"init": lambda c, a: print(f"ready: {a.db}"), "add": cmd_add, "list": cmd_list, "close": cmd_close}[
        args.cmd
    ](conn, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
