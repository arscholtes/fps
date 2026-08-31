"""Where each role's window goes.

Three constraints beyond ranking, and they are not preferences the ranking can
express:

  pilot is always the centre window — it does not compete for its slot
  the arrangement is symmetric around pilot, which wants an odd screen count
  an even screen count has no symmetric answer, so it is handled explicitly

The screens here are the real desk: a built-in at origin(0,0) that macOS calls
MAIN, and an external at origin(-2560,-111) that is physically to its left.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fps_layout  # noqa: E402

BUILTIN = {"idx": 0, "x": 0, "y": 0, "w": 2056, "h": 1329, "main": True}
EXTERNAL = {"idx": 1, "x": -2560, "y": 0, "w": 2560, "h": 1440, "main": False}
THIRD = {"idx": 2, "x": 2056, "y": 0, "w": 1920, "h": 1080, "main": False}
ROLES = ["forge", "pilot", "shepherd", "warden", "mentor"]


class PilotCentreTests(unittest.TestCase):
    """Pilot is the backbone: front and centre, not ranked into place."""

    def test_pilot_takes_the_centre_screen_of_three(self):
        placed = fps_layout.arrange([EXTERNAL, BUILTIN, THIRD], ROLES)
        self.assertEqual(placed["pilot"]["idx"], BUILTIN["idx"])

    def test_pilot_keeps_the_centre_whatever_order_the_roles_arrive_in(self):
        placed = fps_layout.arrange([EXTERNAL, BUILTIN, THIRD], list(reversed(ROLES)))
        self.assertEqual(placed["pilot"]["idx"], BUILTIN["idx"])

    def test_pilot_is_placed_even_when_it_is_the_only_role(self):
        placed = fps_layout.arrange([EXTERNAL, BUILTIN, THIRD], ["pilot"])
        self.assertEqual(placed["pilot"]["idx"], BUILTIN["idx"])

    def test_a_missing_pilot_does_not_break_the_arrangement(self):
        placed = fps_layout.arrange([EXTERNAL, BUILTIN], ["forge", "shepherd"])
        self.assertEqual(len(placed), 2)


class SymmetryTests(unittest.TestCase):
    def test_three_screens_split_two_pilot_two(self):
        placed = fps_layout.arrange([EXTERNAL, BUILTIN, THIRD], ROLES)
        counts = {}
        for role, screen in placed.items():
            counts[screen["idx"]] = counts.get(screen["idx"], 0) + 1
        self.assertEqual(counts[BUILTIN["idx"]], 1)
        self.assertEqual(sorted(v for k, v in counts.items() if k != BUILTIN["idx"]), [2, 2])

    def test_the_split_is_balanced_left_and_right_of_pilot(self):
        placed = fps_layout.arrange([EXTERNAL, BUILTIN, THIRD], ROLES)
        left = [r for r, s in placed.items() if s["x"] < BUILTIN["x"]]
        right = [r for r, s in placed.items() if s["x"] > BUILTIN["x"]]
        self.assertEqual(len(left), len(right))

    def test_two_screens_put_pilot_alone_and_the_rest_together(self):
        # There is no symmetric answer with an even count, so it is stated:
        # one screen is pilot's, the other holds everything else.
        placed = fps_layout.arrange([EXTERNAL, BUILTIN], ROLES)
        pilot_screen = placed["pilot"]["idx"]
        others = {s["idx"] for r, s in placed.items() if r != "pilot"}
        self.assertEqual(others, {EXTERNAL["idx"]})
        self.assertEqual(pilot_screen, BUILTIN["idx"])

    def test_one_screen_puts_everything_on_it_rather_than_failing(self):
        placed = fps_layout.arrange([BUILTIN], ROLES)
        self.assertEqual({s["idx"] for s in placed.values()}, {BUILTIN["idx"]})

    def test_no_screens_places_nothing_rather_than_raising(self):
        self.assertEqual(fps_layout.arrange([], ROLES), {})


class CentreChoiceTests(unittest.TestCase):
    """macOS MAIN and the physically central screen are different here.

    The desktop spans x=-2560 to 2056, so the physical centre is x=-252, which
    falls on the external. The built-in is MAIN. The two readings of "front and
    centre" point at opposite sides of the desk, so it is a setting with a stated
    default rather than a silent choice.
    """

    def test_the_default_is_the_macos_main_display(self):
        placed = fps_layout.arrange([EXTERNAL, BUILTIN], ROLES)
        self.assertEqual(placed["pilot"]["idx"], BUILTIN["idx"])

    def test_the_physical_centre_can_be_chosen_instead(self):
        placed = fps_layout.arrange([EXTERNAL, BUILTIN], ROLES, centre="physical")
        self.assertEqual(placed["pilot"]["idx"], EXTERNAL["idx"])

    def test_the_physical_centre_is_computed_from_the_whole_desktop(self):
        self.assertEqual(fps_layout.centre_screen([EXTERNAL, BUILTIN])["idx"], EXTERNAL["idx"])

    def test_with_one_screen_both_readings_agree(self):
        self.assertEqual(fps_layout.centre_screen([BUILTIN])["idx"], BUILTIN["idx"])


class RectTests(unittest.TestCase):
    def test_a_placed_role_gets_a_rect_inside_its_screen(self):
        rects = {r[0]: r[1:] for r in fps_layout.rects(fps_layout.arrange([BUILTIN], ["pilot"]))}
        left, top, right, bottom = rects["pilot"]
        self.assertGreaterEqual(left, BUILTIN["x"])
        self.assertLessEqual(right, BUILTIN["x"] + BUILTIN["w"])

    def test_negative_origins_survive_into_the_rect(self):
        # The external is at x=-2560 and must stay there; clamping to zero is
        # what the AppleScript applier did and why it could not be targeted.
        rects = {r[0]: r[1:] for r in fps_layout.rects(fps_layout.arrange([EXTERNAL], ["pilot"]))}
        self.assertLess(rects["pilot"][0], 0)


if __name__ == "__main__":
    unittest.main()
