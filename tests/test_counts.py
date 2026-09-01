"""Per-role green/red counts behind the status line dots.

GREEN is claimable work: `bd ready` filtered to a role label. It drains itself.
RED is what is waiting on Alex: human gates, and open loops. It only ever drains
when he acts, so it is the half that silently accumulates.

The counts must be ENUMERABLE. A number nobody can expand into a list becomes
wallpaper, which is the failure his own audit found three times over.
"""

import sys
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


if __name__ == "__main__":
    unittest.main()
