"""A notice carries a fact. A spec goes in a bead.

The charter has said this since it was written and it was ignored anyway: of 45
notices sent, the median body is 1,351 characters and only 2 are under 400. Twelve
of the fifteen sitting unacked in forge's queue on 2026-09-06 were specs, three of
them asking for the same build on three different days, and none of the three ever
became a bead.

Restating the rule was tried. This enforces it instead, because a length nobody can
exceed is the only version of the rule that has ever held.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fps_services  # noqa: E402


class ANoticeIsAFactNotASpec(unittest.TestCase):
    def test_a_fact_passes(self):
        fact = "postgres is down; the client-portal specs cannot run until it is back."
        self.assertIsNone(fps_services.too_long_to_be_a_fact(fact))

    def test_the_shortest_real_notices_still_pass(self):
        # Measured from the live store: the two shortest bodies ever sent, at 296
        # and 358 characters. A cap that rejects real traffic is a cap that gets
        # removed, so these are the floor it must clear.
        self.assertIsNone(fps_services.too_long_to_be_a_fact("x" * 358))

    def test_a_spec_is_refused_and_told_where_to_go(self):
        spec = "BUILD: the transcript store. " + ("schema and rationale. " * 40)
        problem = fps_services.too_long_to_be_a_fact(spec)
        self.assertIsNotNone(problem)
        self.assertIn("bd create", problem)

    def test_the_refusal_names_the_measurement(self):
        problem = fps_services.too_long_to_be_a_fact("y" * 3000)
        self.assertIn(str(fps_services.NOTICE_MAX_CHARS), problem)


if __name__ == "__main__":
    unittest.main()
