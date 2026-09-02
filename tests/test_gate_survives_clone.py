"""The QA gate must survive a fresh clone.

`git rm -r --cached .beads` removed a whole directory when one file in it was
sensitive. issues.jsonl carried an email and a private org name and had to go;
.beads/hooks/* is what wires the gate through core.hooksPath and had to stay.
Removing both left this repo with core.hooksPath pointing at a directory that
does not exist — the gate was dead here, not merely in a clone.

The two halves are asserted together because fixing one by breaking the other is
exactly what happened.
"""

import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOKS = ("pre-commit", "pre-push")
NEVER_TRACKED = ("issues.jsonl", "export-state.json", "last-touched")


def tracked(pattern):
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", pattern],
                         capture_output=True, text=True, check=False)
    return [x for x in out.stdout.split("\n") if x.strip()]


class TheGateIsCloneable(unittest.TestCase):
    def test_hook_files_are_tracked(self):
        names = {Path(p).name for p in tracked(".beads/hooks/*")}
        for hook in HOOKS:
            self.assertIn(hook, names, f"{hook} is not tracked; a clone would have no gate")

    def test_the_hooks_directory_exists_on_disk(self):
        """core.hooksPath points here; if it is missing git silently runs nothing."""
        self.assertTrue((REPO / ".beads" / "hooks").is_dir(),
                        "core.hooksPath target is missing — no hook can run")

    def test_hooks_are_executable(self):
        for hook in HOOKS:
            path = REPO / ".beads" / "hooks" / hook
            if path.exists():
                self.assertTrue(path.stat().st_mode & 0o111, f"{hook} is not executable")


class TheIssueStoreStaysPrivate(unittest.TestCase):
    """The reason the directory was removed in the first place."""

    def test_the_issue_store_is_not_tracked(self):
        for name in NEVER_TRACKED:
            self.assertEqual([], tracked(f".beads/{name}"),
                             f".beads/{name} is tracked and carries private data")

    def test_no_database_is_tracked(self):
        self.assertEqual([], tracked(".beads/*.db"))

    def test_backups_are_not_tracked(self):
        self.assertEqual([], tracked(".beads/backup/*"))


if __name__ == "__main__":
    unittest.main()
