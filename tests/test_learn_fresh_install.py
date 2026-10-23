"""fps-learn works on a machine where nothing has created its data folder yet."""

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fps_learn


class FreshInstallTests(unittest.TestCase):
    def test_connect_creates_the_missing_data_folder(self):
        db = Path(tempfile.mkdtemp()) / "not-yet" / "standup.db"
        conn = fps_learn.connect(db)
        self.addCleanup(conn.close)
        self.assertTrue(db.exists())
        self.assertEqual(conn.execute("SELECT count(*) FROM lessons").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
