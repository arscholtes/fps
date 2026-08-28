"""Tenancy: repo resolution, slugging, and per-repo database files."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fps_tenant  # noqa: E402


class TenantTestCase(unittest.TestCase):
    """Isolates FPS_HOME and clears any binding inherited from the caller."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("FPS_HOME", "FPS_BOUND_REPO", "FPS_REPO", "FPS_NOTICE_TTL_DAYS")}
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["FPS_HOME"] = os.path.join(self._tmp.name, "fpshome")
        for k in ("FPS_BOUND_REPO", "FPS_REPO", "FPS_NOTICE_TTL_DAYS"):
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def make_repo(self, *parts):
        path = os.path.join(self._tmp.name, *parts)
        os.makedirs(path, exist_ok=True)
        return path


class SlugTests(TenantTestCase):
    def test_slug_starts_with_the_repo_basename(self):
        repo = self.make_repo("Developer", "workrepo")
        self.assertTrue(fps_tenant.slug_for(repo).startswith("workrepo-"))

    def test_same_basename_in_two_locations_gets_two_slugs(self):
        a = self.make_repo("work", "workrepo")
        b = self.make_repo("personal", "workrepo")
        self.assertNotEqual(fps_tenant.slug_for(a), fps_tenant.slug_for(b))

    def test_slug_is_stable_across_calls(self):
        repo = self.make_repo("jobhunt")
        self.assertEqual(fps_tenant.slug_for(repo), fps_tenant.slug_for(repo))

    def test_trailing_slash_and_dot_segments_resolve_to_one_slug(self):
        repo = self.make_repo("fps")
        noisy = os.path.join(repo, ".", "")
        self.assertEqual(fps_tenant.slug_for(repo), fps_tenant.slug_for(noisy))

    def test_slug_is_filesystem_safe(self):
        repo = self.make_repo("weird name.with dots")
        slug = fps_tenant.slug_for(repo)
        self.assertNotIn("/", slug)
        self.assertNotIn(" ", slug)


class DbPathTests(TenantTestCase):
    def test_tenant_db_lives_under_fps_home_never_inside_the_repo(self):
        repo = self.make_repo("someproject")
        db = fps_tenant.db_path_for(repo)
        self.assertTrue(db.startswith(os.environ["FPS_HOME"]))
        self.assertFalse(db.startswith(repo))

    def test_global_db_is_not_the_tenant_db(self):
        repo = self.make_repo("someproject")
        self.assertNotEqual(fps_tenant.db_path_for(repo), fps_tenant.global_db_path())


class ResolveTests(TenantTestCase):
    def test_explicit_repo_wins_when_nothing_is_bound(self):
        repo = self.make_repo("explicit")
        self.assertEqual(fps_tenant.resolve_repo(explicit=repo), os.path.realpath(repo))

    def test_bound_repo_is_used_when_no_explicit_repo_given(self):
        repo = self.make_repo("bound")
        os.environ["FPS_BOUND_REPO"] = repo
        self.assertEqual(fps_tenant.resolve_repo(), os.path.realpath(repo))

    def test_explicit_repo_matching_the_binding_is_accepted(self):
        repo = self.make_repo("bound")
        os.environ["FPS_BOUND_REPO"] = repo
        self.assertEqual(fps_tenant.resolve_repo(explicit=repo), os.path.realpath(repo))

    def test_explicit_repo_conflicting_with_the_binding_is_refused(self):
        bound = self.make_repo("bound")
        other = self.make_repo("other")
        os.environ["FPS_BOUND_REPO"] = bound
        with self.assertRaises(fps_tenant.RepoBindingError):
            fps_tenant.resolve_repo(explicit=other)

    def test_missing_directory_is_an_error_rather_than_a_silent_tenant(self):
        with self.assertRaises(fps_tenant.RepoBindingError):
            fps_tenant.resolve_repo(explicit=os.path.join(self._tmp.name, "nope"))

    def test_resolution_never_falls_back_to_cwd_when_bound(self):
        bound = self.make_repo("bound")
        elsewhere = self.make_repo("elsewhere")
        os.environ["FPS_BOUND_REPO"] = bound
        cwd = os.getcwd()
        try:
            os.chdir(elsewhere)
            self.assertEqual(fps_tenant.resolve_repo(), os.path.realpath(bound))
        finally:
            os.chdir(cwd)


class RegistryTests(TenantTestCase):
    def test_joining_records_the_repo(self):
        repo = self.make_repo("newproject")
        fps_tenant.join(repo)
        entries = fps_tenant.list_repos()
        self.assertIn(os.path.realpath(repo), [e["path"] for e in entries])

    def test_joining_twice_does_not_duplicate_the_entry(self):
        repo = self.make_repo("newproject")
        fps_tenant.join(repo)
        fps_tenant.join(repo)
        self.assertEqual(len(fps_tenant.list_repos()), 1)

    def test_registry_survives_a_corrupt_file(self):
        repo = self.make_repo("newproject")
        fps_tenant.join(repo)
        Path(fps_tenant.registry_path()).write_text("{ not json")
        self.assertEqual(fps_tenant.list_repos(), [])

    def test_registry_is_json_keyed_by_slug(self):
        repo = self.make_repo("newproject")
        fps_tenant.join(repo)
        data = json.loads(Path(fps_tenant.registry_path()).read_text())
        self.assertIn(fps_tenant.slug_for(repo), data)


class TenantConnectionTests(TenantTestCase):
    def test_connecting_creates_the_db_file_on_first_use(self):
        repo = self.make_repo("fresh")
        db = fps_tenant.db_path_for(repo)
        self.assertFalse(os.path.exists(db))
        fps_tenant.connect_tenant(repo).close()
        self.assertTrue(os.path.exists(db))

    def test_tenant_db_carries_the_sharded_tables(self):
        repo = self.make_repo("fresh")
        conn = fps_tenant.connect_tenant(repo)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("notices", names)
        self.assertIn("open_loops", names)
        conn.close()

    def test_tenant_db_does_not_carry_the_person_scoped_tables(self):
        repo = self.make_repo("fresh")
        conn = fps_tenant.connect_tenant(repo)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("lessons", names)
        self.assertNotIn("checkins", names)
        conn.close()

    def test_two_repos_do_not_share_notices(self):
        a, b = self.make_repo("alpha"), self.make_repo("beta")
        ca = fps_tenant.connect_tenant(a)
        ca.execute("INSERT INTO notices (for_role, severity, body, created_at) VALUES (?,?,?,?)",
                   ("forge", "warn", "alpha only", "2026-08-28T00:00:00+00:00"))
        ca.commit()
        ca.close()
        cb = fps_tenant.connect_tenant(b)
        self.assertEqual(list(cb.execute("SELECT count(*) FROM notices"))[0][0], 0)
        cb.close()

    def test_connecting_also_joins_the_repo(self):
        repo = self.make_repo("autojoin")
        fps_tenant.connect_tenant(repo).close()
        self.assertIn(os.path.realpath(repo), [e["path"] for e in fps_tenant.list_repos()])


class ConfigTests(TenantTestCase):
    def test_a_repo_with_no_config_gets_an_empty_one(self):
        repo = self.make_repo("plain")
        self.assertEqual(fps_tenant.config_for(repo), {})

    def test_config_is_read_from_fps_home_not_from_inside_the_repo(self):
        repo = self.make_repo("configured")
        path = fps_tenant.config_path_for(repo)
        self.assertTrue(path.startswith(os.environ["FPS_HOME"]))
        self.assertFalse(path.startswith(repo))

    def test_config_values_are_returned(self):
        repo = self.make_repo("configured")
        os.makedirs(os.path.dirname(fps_tenant.config_path_for(repo)), exist_ok=True)
        Path(fps_tenant.config_path_for(repo)).write_text(json.dumps({"ports": "3000:web"}))
        self.assertEqual(fps_tenant.config_for(repo)["ports"], "3000:web")

    def test_a_corrupt_config_degrades_to_empty_rather_than_crashing(self):
        repo = self.make_repo("configured")
        os.makedirs(os.path.dirname(fps_tenant.config_path_for(repo)), exist_ok=True)
        Path(fps_tenant.config_path_for(repo)).write_text("{ not json")
        self.assertEqual(fps_tenant.config_for(repo), {})

    def test_two_repos_sharing_a_basename_get_separate_configs(self):
        a, b = self.make_repo("work", "app"), self.make_repo("personal", "app")
        self.assertNotEqual(fps_tenant.config_path_for(a), fps_tenant.config_path_for(b))


class NoticeAgeOutTests(TenantTestCase):
    def test_default_ttl_is_set(self):
        self.assertGreater(fps_tenant.notice_ttl_days(), 0)

    def test_ttl_is_overridable(self):
        os.environ["FPS_NOTICE_TTL_DAYS"] = "3"
        self.assertEqual(fps_tenant.notice_ttl_days(), 3)

    def test_a_nonsense_ttl_falls_back_to_the_default(self):
        os.environ["FPS_NOTICE_TTL_DAYS"] = "banana"
        self.assertEqual(fps_tenant.notice_ttl_days(), fps_tenant.DEFAULT_NOTICE_TTL_DAYS)


if __name__ == "__main__":
    unittest.main()
