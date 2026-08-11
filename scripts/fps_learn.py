#!/usr/bin/env python3
"""The learning queue: things worth understanding, pushed here by any session.

The point is capture at zero cost. Whoever hits something worth learning writes
one line and keeps working; deciding whether it matters, and going deep on it,
happens later in the mentor session. Categorising at capture time is what kills
these queues.

Usage:
    fps_learn.py add --topic TEXT --why TEXT [--level senior|staff|both]
                     [--source REF] [--from ROLE]
    fps_learn.py list [--all] [--level LEVEL]
    fps_learn.py show ID
    fps_learn.py studied ID
    fps_learn.py drop ID
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import textwrap
from datetime import datetime, timezone

DEFAULT_DB = os.path.expanduser(
    os.environ.get("FPS_DB", "~/Desktop/weekly_standup/daily-standup-agent/standup.db")
)
LEVELS = ("senior", "staff", "both")
# A queue nobody can face is a queue nobody reads. Warn before it gets there.
WARN_COUNT = 20


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def age_days(iso):
    try:
        then = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return 0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).days


def connect(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS lessons (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               topic TEXT NOT NULL,
               why TEXT NOT NULL,
               level TEXT NOT NULL DEFAULT 'both',
               source TEXT,
               added_by TEXT,
               created_at TEXT NOT NULL,
               studied_at TEXT
           )"""
    )
    conn.commit()
    return conn


def cmd_add(conn, args):
    if args.level not in LEVELS:
        print(f"level must be one of {', '.join(LEVELS)}", file=sys.stderr)
        return 1
    conn.execute(
        """INSERT INTO lessons (topic, why, level, source, added_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (args.topic, args.why, args.level, args.source, args.added_by, now()),
    )
    conn.commit()
    print(f"queued for mentor: {args.topic}")
    return 0


def cmd_list(conn, args):
    sql = "SELECT * FROM lessons"
    clauses, params = [], []
    if not args.all:
        clauses.append("studied_at IS NULL")
    if args.level:
        clauses.append("(level = ? OR level = 'both')")
        params.append(args.level)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at ASC"
    rows = list(conn.execute(sql, params))
    if not rows:
        print("nothing queued to learn")
        return 0
    for r in rows:
        mark = "done" if r["studied_at"] else f"{age_days(r['created_at'])}d"
        src = f"  ({r['added_by']})" if r["added_by"] else ""
        print(f"  [{r['id']:>3}] {mark:>5}  {r['level']:<6} {r['topic']}{src}")
    open_count = sum(1 for r in rows if not r["studied_at"])
    if open_count > WARN_COUNT:
        print(f"\n  {open_count} queued — past this many the list stops getting read.")
        print("  Drop what you are honestly never going to study.")
    return 0


def cmd_show(conn, args):
    r = conn.execute("SELECT * FROM lessons WHERE id = ?", (args.id,)).fetchone()
    if not r:
        print(f"no lesson with id {args.id}")
        return 1
    print(f"[{r['id']}] {r['topic']}")
    print(f"     level: {r['level']}   queued: {age_days(r['created_at'])}d ago"
          + (f"   from: {r['added_by']}" if r["added_by"] else ""))
    if r["source"]:
        print(f"     source: {r['source']}")
    print()
    print(textwrap.fill(r["why"], width=88, initial_indent="     ", subsequent_indent="     "))
    return 0


def cmd_studied(conn, args):
    cur = conn.execute(
        "UPDATE lessons SET studied_at = ? WHERE id = ? AND studied_at IS NULL", (now(), args.id)
    )
    conn.commit()
    print(f"marked studied: {args.id}" if cur.rowcount else f"no unstudied lesson with id {args.id}")
    return 0


def cmd_drop(conn, args):
    cur = conn.execute("DELETE FROM lessons WHERE id = ?", (args.id,))
    conn.commit()
    print(f"dropped {args.id}" if cur.rowcount else f"no lesson with id {args.id}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("--topic", required=True)
    p_add.add_argument("--why", required=True)
    p_add.add_argument("--level", default="both")
    p_add.add_argument("--source", default=None)
    p_add.add_argument("--from", dest="added_by", default=None)

    p_list = sub.add_parser("list")
    p_list.add_argument("--all", action="store_true")
    p_list.add_argument("--level", default=None)

    for name in ("show", "studied", "drop"):
        p = sub.add_parser(name)
        p.add_argument("id", type=int)

    args = ap.parse_args()
    conn = connect(args.db)
    return {"add": cmd_add, "list": cmd_list, "show": cmd_show,
            "studied": cmd_studied, "drop": cmd_drop}[args.cmd](conn, args)


if __name__ == "__main__":
    sys.exit(main())
