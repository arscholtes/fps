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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fps_tenant

# One owner for this path, in fps_tenant. Two copies of it drifted apart once
# already, which is how fps_learn ended up reading a file nothing else wrote to.
DEFAULT_DB = Path(os.environ.get("FPS_DB", fps_tenant.GLOBAL_DB)).expanduser()
LEVELS = ("senior", "staff", "both")
# A queue nobody can face is a queue nobody reads. Warn before it gets there.
LIBRARY_NOTE_FROM = 20


def size_note(n):
    """How big the library is, stated as a fact and never as a debt.

    This replaced a warning that said the list stops getting read past a
    threshold and told him to drop what he would not study. That sentence made a
    reference feel like a backlog, and pointed at deleting the best material:
    of the ten most employer-looking entries, eight were general SQL, Rails and
    security lessons that merely happened to surface at work.

    Nothing is ever pruned, so there is no number at which the right response is
    to remove something.

    @param n [Integer] lessons held
    @return [String] "" when the size is not worth mentioning
    """
    if n < LIBRARY_NOTE_FROM:
        return ""
    return f"{n} lessons held — searchable with `fps-learn search <terms>`."


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
    note = size_note(len(rows))
    if note:
        print(f"\n  {note}")
    return 0


def search(conn, terms):
    """Lessons matching every-or-any term, best first.

    Retrieval at read time is the substitute for tagging at capture time —
    categorising as things arrive is what kills these queues. A title match
    outranks a body match because the title is what was being named.

    Studied lessons are included: studied means "worked through", not "gone".

    @param terms [Array<String>] search words, case-insensitive
    @return [Array<Row>] ranked, highest score first
    """
    words = [t.lower() for t in terms if t.strip()]
    if not words:
        return []
    scored = []
    for row in conn.execute("SELECT * FROM lessons"):
        topic = (row["topic"] or "").lower()
        body = " ".join(str(row[f] or "").lower() for f in ("why", "source", "level"))
        score = sum(3 for w in words if w in topic) + sum(1 for w in words if w in body)
        if score:
            scored.append((score, -row["id"], row))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [row for _, _, row in scored]


def cmd_search(conn, args):
    rows = search(conn, args.terms)
    if not rows:
        print(f"no lesson matches {' '.join(args.terms)}")
        return 0
    for r in rows:
        mark = "studied" if r["studied_at"] else f"{age_days(r['created_at'])}d"
        print(f"  [{r['id']:>3}] {mark:>7}  {r['level']:<6} {r['topic']}")
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
    """Remove a bad capture. NOT a pruning tool.

    The library is append-only: nothing is removed to make the count smaller,
    and no command or output proposes it. This survives only for a genuine
    mistake at capture time — a typo, a duplicate — and demands an explicit flag
    so it can never be reached by habit.
    """
    if not getattr(args, "mistake", False):
        print("lessons are append-only; nothing is removed to shrink the list.")
        print("if this was a bad capture, re-run with --mistake.")
        return 1
    cur = conn.execute("DELETE FROM lessons WHERE id = ?", (args.id,))
    conn.commit()
    print(f"removed bad capture {args.id}" if cur.rowcount else f"no lesson with id {args.id}")
    return 0


def build_parser():
    """@return [ArgumentParser] the CLI surface. `drop` is deliberately absent
    from help: an escape hatch that is advertised becomes a habit."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    # metavar is set explicitly so `drop` stays out of the listing: argparse
    # prints every subparser name in the choices line, help=SUPPRESS or not.
    sub = ap.add_subparsers(dest="cmd", required=True,
                            metavar="{add,list,search,show,studied}")

    p_add = sub.add_parser("add")
    p_add.add_argument("--topic", required=True)
    p_add.add_argument("--why", required=True)
    p_add.add_argument("--level", default="both")
    p_add.add_argument("--source", default=None)
    p_add.add_argument("--from", dest="added_by", default=None)

    p_list = sub.add_parser("list")
    p_list.add_argument("--all", action="store_true")
    p_list.add_argument("--level", default=None)

    p_search = sub.add_parser("search", help="find lessons by term")
    p_search.add_argument("terms", nargs="+")

    for name in ("show", "studied"):
        p = sub.add_parser(name)
        p.add_argument("id", type=int)

    p_drop = sub.add_parser("drop")
    p_drop.add_argument("id", type=int)
    p_drop.add_argument("--mistake", action="store_true")
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    conn = connect(args.db)
    return {"add": cmd_add, "list": cmd_list, "show": cmd_show, "search": cmd_search,
            "studied": cmd_studied, "drop": cmd_drop}[args.cmd](conn, args)


if __name__ == "__main__":
    sys.exit(main())
