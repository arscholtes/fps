"""`notices` must not report absence it did not check.

Notices live in per-repo tenant databases. Run from one repo, the empty case
printed a bare "no notices" — a claim about the whole system from a query that
had looked at one tenant. On 2026-09-09 it said that while a pending-work
batch sat unread in the jobhunt tenant and a P1 from herald sat unread in
lesson-platform.

This is the same defect already fixed in `fps-loops list`, found the same way:
the reassuring reading was the wrong one and nothing compared the two.
"""
import io
import sqlite3
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fps_services
import fps_tenant


def _empty_tenant():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE notices (id INTEGER PRIMARY KEY, for_role TEXT,"
        " severity TEXT, body TEXT, created_at TEXT, acked_at TEXT,"
        " from_role TEXT);")
    return conn


class Args:
    all = False
    for_role = "pilot"
    quiet = False


class EmptyNamesWhatItSearched(unittest.TestCase):
    def test_empty_result_names_the_repo_not_the_world(self):
        out = io.StringIO()
        with patch.object(fps_tenant, "list_repos", return_value=[]), redirect_stdout(out):
            fps_services.cmd_notices(_empty_tenant(), Args(), repo="/Users/a/Developer/fps")
        self.assertIn("fps", out.getvalue())
        self.assertNotEqual(out.getvalue().strip(), "no notices")

    def test_unread_elsewhere_is_surfaced(self):
        out = io.StringIO()
        elsewhere = [{"slug": "jobhunt-43a0", "path": "/Users/a/Developer/jobhunt"}]
        rows = [{"id": 5, "for_role": "pilot", "severity": "warn",
                 "body": "WEEKLY BATCH — 8 roles ready", "created_at": "2026-09-08",
                 "acked_at": None, "from_role": "forge"}]
        with patch.object(fps_tenant, "list_repos", return_value=elsewhere), \
             patch.object(fps_services, "_unacked_rows", return_value=rows), \
             redirect_stdout(out):
            fps_services.cmd_notices(_empty_tenant(), Args(), repo="/Users/a/Developer/fps")
        printed = out.getvalue()
        self.assertIn("jobhunt", printed)
        self.assertIn("WEEKLY BATCH", printed)


if __name__ == "__main__":
    unittest.main()
