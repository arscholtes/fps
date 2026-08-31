"""Reading the worktree a service process belongs to, out of its proctitle.

This was a hardcoded repo name, which made it wrong twice over: it published a
name that must not appear in this repo, and it only ever matched ONE repo. Once
FPS went multi-tenant every other repo silently got worktree=None, which is
indistinguishable from "this is the main checkout".

The test that matters is the last one: the pattern has to work for a repo whose
name nobody wrote into the source.
"""

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fps_services

SIDEKIQ = ("sidekiq 7.2.0 [0 of 10 busy] "
           "/Users/someone/Developer/{repo}/{checkout} -C config/sidekiq-dev.yml")


class WorktreeFromProctitle(unittest.TestCase):
    def test_named_worktree_is_returned(self):
        cmd = SIDEKIQ.format(repo="myapp", checkout="myapp-featurebranch")
        self.assertEqual("myapp-featurebranch", fps_services.worktree_from(cmd, "myapp"))

    def test_main_checkout_is_not_a_worktree(self):
        cmd = SIDEKIQ.format(repo="myapp", checkout="myapp")
        self.assertIsNone(fps_services.worktree_from(cmd, "myapp"))

    def test_works_for_any_repo_name(self):
        """The regression guard. A hardcoded name passes the two tests above for
        exactly one repo and returns None for every other one."""
        for repo in ("jobhunt", "tts", "daily-standup-agent", "some-other-repo"):
            with self.subTest(repo=repo):
                wt = f"{repo}-spike"
                self.assertEqual(wt, fps_services.worktree_from(
                    SIDEKIQ.format(repo=repo, checkout=wt), repo))
                self.assertIsNone(fps_services.worktree_from(
                    SIDEKIQ.format(repo=repo, checkout=repo), repo))

    def test_unrelated_process_yields_nothing(self):
        self.assertIsNone(fps_services.worktree_from("puma 6.4.2 (tcp://0.0.0.0:3000)", "myapp"))

    def test_a_repo_name_that_is_a_regex_metacharacter_is_escaped(self):
        cmd = SIDEKIQ.format(repo="my.app", checkout="my.app-branch")
        self.assertEqual("my.app-branch", fps_services.worktree_from(cmd, "my.app"))
        self.assertIsNone(fps_services.worktree_from(
            SIDEKIQ.format(repo="myXapp", checkout="myXapp"), "my.app"))

    def test_a_file_sharing_the_repo_prefix_is_not_a_worktree(self):
        """Found by running it, not by reading it: a live scan reported the
        worktree 'fps_services' for a process running fps_services.py, because
        underscore is a word character. A worktree is a DIRECTORY named
        <repo>-<branch>, so the match has to be a whole path segment."""
        for cmd in ("sidekiq /Users/a/Developer/fps/fps -C x.yml python3 scripts/fps_services.py",
                    "sidekiq python3 /Users/a/fps/fps_tenant.py",
                    "sidekiq /Users/a/fpsbackup/thing"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(fps_services.worktree_from(cmd, "fps"))

    def test_worktree_must_be_hyphen_separated_from_the_repo_name(self):
        self.assertEqual("fps-lint", fps_services.worktree_from(
            "sidekiq /Users/a/Developer/fps/fps-lint -C x.yml", "fps"))

    def test_missing_repo_name_is_not_a_match_against_everything(self):
        cmd = SIDEKIQ.format(repo="myapp", checkout="myapp-branch")
        self.assertIsNone(fps_services.worktree_from(cmd, ""))
        self.assertIsNone(fps_services.worktree_from(cmd, None))


class ProcessListingUsesTheBoundRepo(unittest.TestCase):
    def test_app_processes_takes_the_repo_it_was_given(self):
        sig = inspect.signature(fps_services.app_processes)
        self.assertIn("repo", sig.parameters,
                      "app_processes must be told which repo it is reporting on")


if __name__ == "__main__":
    unittest.main()
