"""Per-role green/red counts behind the status line dots.

GREEN is claimable work: `bd ready` filtered to a role label. It drains itself.
RED is what is waiting on Alex: human gates, and open loops. It only ever drains
when he acts, so it is the half that silently accumulates.

The counts must be ENUMERABLE. A number nobody can expand into a list becomes
wallpaper, which is the failure his own audit found three times over.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fps_counts

READY = [
    {"id": "x-1", "labels": ["forge"], "issue_type": "task", "status": "open"},
    {"id": "x-2", "labels": ["forge"], "issue_type": "task", "status": "open"},
    {"id": "x-3", "labels": ["mentor"], "issue_type": "task", "status": "open"},
    {"id": "x-4", "labels": None, "issue_type": "task", "status": "open"},
    {"id": "x-5", "labels": ["demo"], "issue_type": "task", "status": "open"},
]
GATES = [
    {"id": "g-1", "issue_type": "gate", "status": "open", "title": "Gate: human",
     "blocks": [{"id": "x-1", "labels": ["forge"]}]},
    {"id": "g-2", "issue_type": "gate", "status": "open", "title": "Gate: human",
     "blocks": [{"id": "x-4", "labels": None}]},
]


class GreenCounts(unittest.TestCase):
    def test_counts_ready_work_by_role_label(self):
        g = fps_counts.green_counts(READY)
        self.assertEqual(2, g["forge"])
        self.assertEqual(1, g["mentor"])

    def test_roles_with_no_labelled_work_are_zero_not_missing(self):
        g = fps_counts.green_counts(READY)
        for role in fps_counts.ROLES:
            self.assertIn(role, g)
        self.assertEqual(0, g["pilot"])

    def test_a_non_role_label_is_not_a_role(self):
        self.assertNotIn("demo", fps_counts.green_counts(READY))

    def test_unlabelled_work_counts_for_nobody(self):
        self.assertEqual(3, sum(fps_counts.green_counts(READY).values()))


class RedItems(unittest.TestCase):
    def test_a_gate_is_attributed_to_the_role_it_blocks(self):
        items = fps_counts.red_items(GATES, loops=[])
        self.assertEqual("forge", next(i for i in items if i["id"] == "g-1")["role"])

    def test_a_gate_blocking_unlabelled_work_is_unattributed_not_dropped(self):
        items = fps_counts.red_items(GATES, loops=[])
        g2 = next(i for i in items if i["id"] == "g-2")
        self.assertIsNone(g2["role"])
        self.assertEqual(2, len(items), "an unattributable gate must still be counted somewhere")

    def test_unresolved_loops_are_red(self):
        loops = [{"id": 1, "question": "which approach?", "asked_of": "neil", "resolved_at": None}]
        items = fps_counts.red_items([], loops=loops)
        self.assertEqual(1, len(items))
        self.assertEqual("loop", items[0]["kind"])

    def test_resolved_loops_are_not_red(self):
        loops = [{"id": 1, "question": "q", "asked_of": "x", "resolved_at": "2026-08-01"}]
        self.assertEqual([], fps_counts.red_items([], loops=loops))

    def test_closed_gates_are_not_red(self):
        closed = [dict(GATES[0], status="closed")]
        self.assertEqual([], fps_counts.red_items(closed, loops=[]))

    def test_every_item_carries_enough_to_display_it(self):
        for item in fps_counts.red_items(GATES, loops=[]):
            self.assertTrue(item.get("id"))
            self.assertTrue(item.get("what"), f"{item['id']} has nothing to show a human")


class TheSnapshot(unittest.TestCase):
    def test_shape_is_every_role_with_both_numbers(self):
        snap = fps_counts.snapshot(ready=READY, gates=GATES, loops=[])
        for role in fps_counts.ROLES:
            self.assertIn("green", snap["roles"][role])
            self.assertIn("red", snap["roles"][role])

    def test_unattributed_red_is_reported_separately_not_hidden(self):
        snap = fps_counts.snapshot(ready=READY, gates=GATES, loops=[])
        self.assertEqual(1, snap["unattributed"])
        self.assertEqual(1, snap["roles"]["forge"]["red"])

    def test_carries_the_time_it_was_generated(self):
        """The writer runs on a timer; a reader must be able to tell it went stale."""
        self.assertIn("generated_at", fps_counts.snapshot(ready=[], gates=[], loops=[]))

    def test_totals_reconcile_with_the_item_list(self):
        snap = fps_counts.snapshot(ready=READY, gates=GATES, loops=[])
        counted = sum(r["red"] for r in snap["roles"].values()) + snap["unattributed"]
        self.assertEqual(len(fps_counts.red_items(GATES, loops=[])), counted,
                         "the dots and the enumerable list must not disagree")


class MissingBeadsIsLoud(unittest.TestCase):
    """An empty queue and a broken writer must not look the same.

    The 15s writer runs under launchd with a minimal PATH. bd was not on it, so
    every count came back zero — indistinguishable from a quiet system, and the
    status line reported it as fact.
    """

    def test_a_missing_bd_raises_rather_than_returning_nothing(self):
        saved = os.environ["PATH"]
        os.environ["PATH"] = "/nonexistent"
        try:
            with self.assertRaises(fps_counts.BeadsUnavailable):
                fps_counts._bd("/tmp", "ready")
        finally:
            os.environ["PATH"] = saved


class AcrossRepos(unittest.TestCase):
    """Counts cover every repo, not the bound one.

    Beads is per-repo, but Alex's sessions are bound to a repo where beads is
    empty, so a per-repo count rendered blank in the terminal he actually sits
    in. The dots answer "what does this node have", which is a question about
    the node rather than about a checkout.
    """

    def test_green_sums_across_repos(self):
        merged = fps_counts.merge([
            fps_counts.snapshot(ready=[{"id": "a", "labels": ["forge"]}], gates=[], loops=[]),
            fps_counts.snapshot(ready=[{"id": "b", "labels": ["forge"]},
                                       {"id": "c", "labels": ["pilot"]}], gates=[], loops=[]),
        ])
        self.assertEqual(2, merged["roles"]["forge"]["green"])
        self.assertEqual(1, merged["roles"]["pilot"]["green"])

    def test_red_and_unattributed_sum_too(self):
        one = fps_counts.snapshot(ready=[], gates=GATES, loops=[])
        merged = fps_counts.merge([one, one])
        self.assertEqual(2, merged["roles"]["forge"]["red"])
        self.assertEqual(2, merged["unattributed"])

    def test_items_say_which_repo_they_came_from(self):
        """Aggregating must not lose where the work is, or the list stops being
        actionable."""
        snap = fps_counts.snapshot(ready=[], gates=GATES, loops=[])
        snap["repo"] = "/x/fps"
        merged = fps_counts.merge([snap])
        self.assertTrue(all(i.get("repo") for i in merged["items"]))

    def test_merging_nothing_is_an_empty_system_not_a_crash(self):
        merged = fps_counts.merge([])
        self.assertEqual(0, merged["roles"]["forge"]["green"])
        self.assertIn("generated_at", merged)


class MissingBeadsIsNotAnEmptyQueue(unittest.TestCase):
    """A repo bd cannot read must not report the same thing as a quiet one.

    _bd() raised on a missing binary for exactly this reason, then returned []
    one branch over when bd ran and exited non-zero. Six of eight joined repos
    have no .beads at all, so every 15s cycle turned "cannot answer" into
    "nothing ready" — the shape the launchd PATH incident already cost once.
    """

    def test_a_repo_bd_cannot_read_raises_rather_than_reporting_nothing(self):
        with tempfile.TemporaryDirectory() as d, \
             self.assertRaises(fps_counts.BeadsUnavailable) as caught:
            fps_counts._bd(d, "ready")
        # Distinguishes a non-zero exit from the missing-binary path, which
        # would otherwise satisfy this test for the wrong reason.
        self.assertIn("exit", str(caught.exception))

    def test_a_beadsless_repo_is_marked_unavailable_not_quiet(self):
        with tempfile.TemporaryDirectory() as d:
            snap = fps_counts.write_snapshot(d, path=Path(d) / "snap.json")
        self.assertFalse(snap["available"])
        self.assertEqual(0, snap["roles"]["forge"]["green"])

    def test_merge_reports_which_repos_could_not_be_read(self):
        readable = fps_counts.snapshot(ready=[], gates=[], loops=[])
        readable.update(repo="/x/fps", available=True)
        blind = fps_counts.snapshot(ready=[], gates=[], loops=[])
        blind.update(repo="/x/workrepo", available=False)
        merged = fps_counts.merge([readable, blind])
        self.assertEqual(["workrepo"], merged["unavailable"])

    def test_a_fully_readable_system_names_nothing_unavailable(self):
        one = fps_counts.snapshot(ready=[], gates=[], loops=[])
        one.update(repo="/x/fps", available=True)
        self.assertEqual([], fps_counts.merge([one])["unavailable"])


if __name__ == "__main__":
    unittest.main()
