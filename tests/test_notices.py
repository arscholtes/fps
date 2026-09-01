"""Notice delivery: per-repo isolation and the age-out backstop."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sqlite3

import fps_services
import fps_tenant


def days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat(timespec="seconds")


class NoticeTestCase(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("FPS_HOME", "FPS_BOUND_REPO", "FPS_REPO", "FPS_NOTICE_TTL_DAYS")}
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["FPS_HOME"] = str(Path(self._tmp.name) / "fpshome")
        for k in ("FPS_BOUND_REPO", "FPS_REPO", "FPS_NOTICE_TTL_DAYS"):
            os.environ.pop(k, None)
        self.repo = str(Path(self._tmp.name) / "repo")
        Path(self.repo).mkdir(parents=True)
        self.conn = fps_tenant.connect_tenant(self.repo)

    def tearDown(self):
        self.conn.close()
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def add(self, body, role="forge", created_at=None, acked=False):
        cur = self.conn.execute(
            "INSERT INTO notices (for_role, severity, body, created_at, acked_at) VALUES (?,?,?,?,?)",
            (role, "warn", body, created_at or days_ago(0), days_ago(0) if acked else None))
        self.conn.commit()
        return cur.lastrowid

    def listing(self, **kw):
        opts = {"all": False, "quiet": False, "for_role": "forge"}
        opts.update(kw)
        args = SimpleNamespace(**opts)
        buf = io.StringIO()
        with redirect_stdout(buf):
            fps_services.cmd_notices(self.conn, args)
        return buf.getvalue()


class DeliveryTests(NoticeTestCase):
    def test_a_fresh_notice_is_delivered(self):
        self.add("build the thing")
        self.assertIn("build the thing", self.listing())

    def test_an_acked_notice_is_not_delivered(self):
        self.add("already handled", acked=True)
        self.assertNotIn("already handled", self.listing())

    def test_a_notice_for_another_role_is_not_delivered(self):
        self.add("for the shepherd", role="shepherd")
        self.assertNotIn("for the shepherd", self.listing())

    def test_a_notice_for_everyone_is_delivered(self):
        self.add("for all", role=None)
        self.assertIn("for all", self.listing())


class AgeOutTests(NoticeTestCase):
    def test_a_notice_past_the_ttl_is_hidden(self):
        os.environ["FPS_NOTICE_TTL_DAYS"] = "14"
        self.add("ancient", created_at=days_ago(30))
        self.assertNotIn("ancient", self.listing())

    def test_a_notice_inside_the_ttl_survives(self):
        os.environ["FPS_NOTICE_TTL_DAYS"] = "14"
        self.add("recent", created_at=days_ago(13))
        self.assertIn("recent", self.listing())

    def test_aged_out_notices_are_counted_in_a_footer_not_silently_dropped(self):
        os.environ["FPS_NOTICE_TTL_DAYS"] = "14"
        self.add("ancient one", created_at=days_ago(30))
        self.add("ancient two", created_at=days_ago(40))
        out = self.listing()
        self.assertIn("2", out)
        self.assertIn("aged out", out.lower())

    def test_all_still_shows_aged_out_notices(self):
        os.environ["FPS_NOTICE_TTL_DAYS"] = "14"
        self.add("ancient", created_at=days_ago(30))
        self.assertIn("ancient", self.listing(all=True))

    def test_age_out_never_deletes_the_row(self):
        os.environ["FPS_NOTICE_TTL_DAYS"] = "14"
        self.add("ancient", created_at=days_ago(30))
        self.listing()
        self.assertEqual(self.conn.execute("SELECT count(*) FROM notices").fetchone()[0], 1)

    def test_quiet_listing_of_only_aged_out_notices_prints_nothing(self):
        os.environ["FPS_NOTICE_TTL_DAYS"] = "14"
        self.add("ancient", created_at=days_ago(30))
        self.assertEqual(self.listing(quiet=True).strip(), "")


class AckTests(NoticeTestCase):
    def test_acking_removes_a_notice_from_the_default_listing(self):
        nid = self.add("do the work")
        buf = io.StringIO()
        with redirect_stdout(buf):
            fps_services.cmd_ack(self.conn, SimpleNamespace(id=nid))
        self.assertNotIn("do the work", self.listing())

    def test_acking_an_unknown_id_reports_rather_than_pretending(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            fps_services.cmd_ack(self.conn, SimpleNamespace(id=9999))
        self.assertIn("no open notice", buf.getvalue())


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("FPS_HOME", "FPS_GLOBAL_DB", "FPS_BOUND_REPO")}
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["FPS_HOME"] = str(Path(self._tmp.name) / "fpshome")
        os.environ["FPS_GLOBAL_DB"] = str(Path(self._tmp.name) / "standup.db")
        os.environ.pop("FPS_BOUND_REPO", None)
        self.repo = str(Path(self._tmp.name) / "repo")
        Path(self.repo).mkdir(parents=True)

        g = sqlite3.connect(os.environ["FPS_GLOBAL_DB"])
        for stmt in fps_tenant.TENANT_SCHEMA:
            g.execute(stmt)
        g.execute("CREATE TABLE lessons (id INTEGER PRIMARY KEY, topic TEXT)")
        g.execute("INSERT INTO notices (for_role, severity, body, created_at) "
                  "VALUES ('forge','warn','legacy notice','2026-08-20T00:00:00+00:00')")
        g.execute("INSERT INTO open_loops (asked_of, question, asked_at) "
                  "VALUES ('someone','a question','2026-08-20T00:00:00+00:00')")
        g.execute("INSERT INTO lessons (topic) VALUES ('a lesson')")
        g.commit()
        g.close()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def test_migration_copies_repo_scoped_rows_into_the_tenant(self):
        fps_tenant.migrate_from_global(self.repo)
        conn = fps_tenant.connect_tenant(self.repo)
        self.assertEqual(conn.execute("SELECT count(*) FROM notices").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT count(*) FROM open_loops").fetchone()[0], 1)
        conn.close()

    def test_migration_leaves_the_global_database_intact(self):
        fps_tenant.migrate_from_global(self.repo)
        g = sqlite3.connect(os.environ["FPS_GLOBAL_DB"])
        self.assertEqual(g.execute("SELECT count(*) FROM lessons").fetchone()[0], 1)
        self.assertEqual(g.execute("SELECT count(*) FROM notices").fetchone()[0], 1)
        g.close()

    def test_migration_is_idempotent(self):
        fps_tenant.migrate_from_global(self.repo)
        fps_tenant.migrate_from_global(self.repo)
        conn = fps_tenant.connect_tenant(self.repo)
        self.assertEqual(conn.execute("SELECT count(*) FROM notices").fetchone()[0], 1)
        conn.close()

    def test_migration_does_not_copy_person_scoped_tables(self):
        fps_tenant.migrate_from_global(self.repo)
        conn = fps_tenant.connect_tenant(self.repo)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("lessons", names)
        conn.close()


if __name__ == "__main__":
    unittest.main()
