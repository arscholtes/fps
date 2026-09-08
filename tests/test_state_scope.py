"""`fps-loops list` must not report absence it did not check.

Loops live in per-repo tenant databases, but the empty-result message was
system-wide: run from a repo with none, it printed "no open loops" while four
job applications sat open in the jobhunt tenant. The status line counted them
correctly, so the two disagreed and the more reassuring one was wrong.
"""
import io
import sqlite3
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fps_state
import fps_tenant


def _empty_tenant():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE open_loops (id INTEGER PRIMARY KEY, asked_of TEXT,"
        " question TEXT, asked_at TEXT, resolved_at TEXT, where_url TEXT);")
    return conn


class Args:
    all = False


class ListNamesWhatItSearched(unittest.TestCase):
    def test_empty_result_names_the_repo_rather_than_the_world(self):
        out = io.StringIO()
        with patch.object(fps_tenant, "list_repos", return_value=[]), redirect_stdout(out):
            fps_state.cmd_list(_empty_tenant(), Args(), repo="/Users/a/Developer/fps")
        self.assertIn("fps", out.getvalue())
        self.assertNotEqual(out.getvalue().strip(), "no open loops")

    def test_open_loops_elsewhere_are_pointed_at(self):
        out = io.StringIO()
        elsewhere = [{"slug": "jobhunt-43a0", "path": "/Users/a/Developer/jobhunt"}]
        with patch.object(fps_tenant, "list_repos", return_value=elsewhere), \
             patch.object(fps_state, "_open_rows", return_value=[
                 {"id": 1, "asked_at": "2026-09-06T00:00:00+00:00",
                  "asked_of": "a recruiter", "question": "Application sent"}]), \
             redirect_stdout(out):
            fps_state.cmd_list(_empty_tenant(), Args(), repo="/Users/a/Developer/fps")
        printed = out.getvalue()
        self.assertIn("jobhunt", printed)
        # Showing them beats naming a command the session binding forbids.
        self.assertIn("a recruiter", printed)


if __name__ == "__main__":
    unittest.main()
