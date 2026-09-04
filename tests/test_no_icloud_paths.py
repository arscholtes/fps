"""No source file may reference the iCloud-backed Desktop path.

An evicted file there stats instantly and then blocks in sqlite3.connect, in an
uninterruptible read that signal.alarm does not interrupt. It was read at the start
of every tab, so every session paid for it, and no timeout could have saved them.

This is a guard rather than a style rule: the path was reintroduced once already,
by a second copy of the constant drifting from the first. Both assertions read the
source rather than importing it, because the defect being guarded is a literal in a
file, not a runtime value.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN = "weekly_standup"


class NoSourceReferencesTheICloudPath(unittest.TestCase):
    def test_no_script_or_test_names_the_desktop_database(self):
        here = pathlib.Path(__file__).name
        offenders = [
            str(p.relative_to(ROOT))
            for p in list(ROOT.glob("scripts/*.py")) + list(ROOT.glob("tests/*.py"))
            if p.name != here and FORBIDDEN in p.read_text()
        ]
        self.assertEqual(offenders, [], f"iCloud path reintroduced in: {offenders}")

    def test_the_global_database_is_under_local_share(self):
        src = (ROOT / "scripts" / "fps_tenant.py").read_text()
        m = re.search(r'^GLOBAL_DB = "([^"]+)"', src, re.M)
        self.assertIsNotNone(m, "GLOBAL_DB is no longer a plain string literal")
        self.assertNotIn("Desktop", m.group(1))
        self.assertIn(".local/share", m.group(1))


if __name__ == "__main__":
    unittest.main()
