"""fps-learn as a REFERENCE, not a queue.

55 captured and 1 studied read as a debt only because the tool framed it that
way. Nobody reads GitLab's doc/development front to back either — 642 files sit
there and get retrieved when relevant. As a reference the cost of keeping is
zero and "which do I drop" stops being a question.

Retrieval is what a reference needs, so search is the missing primitive. There
is deliberately no tagging or taxonomy at capture time: categorising at capture
is what kills these queues, and searching at read time is the substitute.
"""

import io
import sqlite3
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fps_learn

LESSONS = [
    ("tenant-scoped outer query does not protect a grouped subquery",
     "The outer scope is applied after grouping, so the subquery sees every account.",
     "staff", "PR #1273", None),
    ("rescue_from StandardError hides exceptions from the test harness",
     "A broad rescue swallows the failure the spec was written to catch.",
     "senior", "spec/requests", None),
    ("the same ILIKE helper exists in two controllers, one sanitised",
     "Duplicated query building drifts, and the copy without sanitisation is injectable.",
     "both", "app/controllers", "2026-08-01"),
    ("LEFT JOIN to a filtered subquery bounds aggregation, not sort",
     "The join narrows what is summed; it does nothing for the ordering cost.",
     "staff", None, None),
]


class SearchTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """CREATE TABLE lessons (id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL,
               why TEXT NOT NULL, level TEXT NOT NULL DEFAULT 'both', source TEXT,
               added_by TEXT, created_at TEXT NOT NULL, studied_at TEXT)""")
        for topic, why, level, source, studied in LESSONS:
            self.conn.execute(
                "INSERT INTO lessons (topic,why,level,source,added_by,created_at,studied_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (topic, why, level, source, "forge", "2026-08-01T00:00:00+00:00", studied))
        self.conn.commit()

    def hits(self, *terms):
        return [r["id"] for r in fps_learn.search(self.conn, list(terms))]

    def out(self, *terms):
        buf = io.StringIO()
        with redirect_stdout(buf):
            fps_learn.cmd_search(self.conn, type("A", (), {"terms": list(terms)})())
        return buf.getvalue()


class Retrieval(SearchTestCase):
    def test_finds_by_a_word_in_the_topic(self):
        self.assertIn(1, self.hits("subquery"))

    def test_finds_by_a_word_in_the_body(self):
        self.assertIn(2, self.hits("swallows"))

    def test_finds_by_source(self):
        self.assertIn(1, self.hits("1273"))

    def test_is_case_insensitive(self):
        self.assertEqual(self.hits("SUBQUERY"), self.hits("subquery"))

    def test_a_studied_lesson_is_still_searchable(self):
        """The whole point of the reframe. Studied means 'worked through', not
        'discharged and gone'."""
        self.assertIn(3, self.hits("ILIKE"))

    def test_no_match_says_so_without_erroring(self):
        self.assertEqual([], self.hits("kubernetes"))
        self.assertIn("no lesson", self.out("kubernetes").lower())


class Ranking(SearchTestCase):
    def test_more_matched_terms_ranks_higher(self):
        ranked = self.hits("subquery", "grouped")
        self.assertEqual(1, ranked[0])

    def test_a_topic_match_outranks_a_body_only_match(self):
        """Both mention 'subquery'; only one has it in the title."""
        ranked = self.hits("subquery")
        self.assertEqual(1, ranked[0])
        self.assertIn(4, ranked)

    def test_results_are_ordered_best_first(self):
        self.assertEqual(self.hits("subquery"), sorted(
            self.hits("subquery"), key=lambda i: self.hits("subquery").index(i)))


class NotADebt(unittest.TestCase):
    """The threshold warning told him to delete a reference. It must not."""

    def test_the_size_report_does_not_tell_him_to_drop_anything(self):
        text = fps_learn.size_note(55)
        self.assertNotIn("drop", text.lower())
        self.assertNotIn("stops getting read", text.lower())

    def test_the_size_report_still_states_the_size(self):
        self.assertIn("55", fps_learn.size_note(55))

    def test_a_small_library_needs_no_note_at_all(self):
        self.assertEqual("", fps_learn.size_note(3))


class AppendOnly(unittest.TestCase):
    """Nothing is ever pruned. Keeping is free, so the count is a library size,
    never a backlog to reduce, and no output may imply otherwise."""

    def test_no_output_ever_suggests_pruning(self):
        for n in (0, 3, 20, 21, 55, 500):
            note = fps_learn.size_note(n).lower()
            for word in ("drop", "prune", "delete", "clean up", "backlog", "too many"):
                self.assertNotIn(word, note, f"size_note({n}) suggests pruning: {note!r}")

    def test_drop_is_not_an_ordinary_command(self):
        """It survives only as an escape hatch for a bad capture, behind an
        explicit flag, and is never proposed."""
        parser = fps_learn.build_parser()
        help_text = parser.format_help().lower()
        self.assertNotIn("drop", help_text, "drop must not be advertised in help")

    def test_dropping_without_the_explicit_flag_refuses(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE lessons (id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL,
               why TEXT NOT NULL, level TEXT NOT NULL DEFAULT 'both', source TEXT,
               added_by TEXT, created_at TEXT NOT NULL, studied_at TEXT)""")
        conn.execute("INSERT INTO lessons (topic,why,level,created_at)"
                     " VALUES ('t','w','both','2026-01-01')")
        conn.commit()
        args = type("A", (), {"id": 1, "mistake": False})()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = fps_learn.cmd_drop(conn, args)
        self.assertEqual(1, rc)
        self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0],
                         "an unflagged drop must not remove anything")


if __name__ == "__main__":
    unittest.main()
