"""The staleness marker must outlive one scheduling interval.

The counts writer moved from launchd at 15s to Hermes cron. Hermes rejects
sub-minute schedules and coalesces a '1m' job to roughly two, measured at
14:39:48, 14:41:48, 14:43:48. With the threshold at 60s the status line flagged
itself stale between every run, and a warning that fires during correct operation
teaches people to ignore it.

The threshold has to clear the interval with room for a slow run, while staying
short enough that a writer which actually died is still caught quickly.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CRON_INTERVAL_SECONDS = 120   # measured: Hermes coalesces a '1m' job to ~2m


def _stale_after(path):
    for line in path.read_text().splitlines():
        if line.startswith("STALE_AFTER"):
            return float(line.split("=")[1].split("#")[0].strip())
    raise AssertionError(f"no STALE_AFTER in {path}")


class StalenessThreshold(unittest.TestCase):
    paths = (ROOT / "scripts/fps_counts.py",
             Path("~/.claude/statusline-fps.py").expanduser())

    def test_clears_one_interval_with_headroom(self):
        for p in self.paths:
            if not p.exists():
                continue
            self.assertGreaterEqual(_stale_after(p), CRON_INTERVAL_SECONDS * 2,
                                    f"{p.name} would flag a healthy writer as stale")

    def test_still_catches_a_writer_that_died(self):
        for p in self.paths:
            if not p.exists():
                continue
            self.assertLessEqual(_stale_after(p), 600,
                                 f"{p.name} would hide a dead writer for too long")

    def test_both_readers_agree(self):
        values = {_stale_after(p) for p in self.paths if p.exists()}
        self.assertEqual(len(values), 1, f"thresholds disagree: {values}")


if __name__ == "__main__":
    unittest.main()
