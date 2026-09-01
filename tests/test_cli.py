"""The --repo flag, and the refusal that keeps a session on one repo."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fps_services
import fps_state


class ParserPositionTests(unittest.TestCase):
    """--repo must work on either side of the subcommand; people type both."""

    def test_services_accepts_repo_before_the_subcommand(self):
        args = fps_services.build_parser().parse_args(["--repo", "/tmp", "notices"])
        self.assertEqual(args.repo, "/tmp")

    def test_services_accepts_repo_after_the_subcommand(self):
        args = fps_services.build_parser().parse_args(["notices", "--repo", "/tmp"])
        self.assertEqual(args.repo, "/tmp")

    def test_services_repo_defaults_to_none(self):
        self.assertIsNone(fps_services.build_parser().parse_args(["notices"]).repo)

    def test_services_subcommand_repo_does_not_clobber_the_leading_one(self):
        args = fps_services.build_parser().parse_args(["--repo", "/tmp", "notices", "--for", "forge"])
        self.assertEqual(args.repo, "/tmp")
        self.assertEqual(args.for_role, "forge")

    def test_state_accepts_repo_after_the_subcommand(self):
        args = fps_state.build_parser().parse_args(["list", "--repo", "/tmp"])
        self.assertEqual(args.repo, "/tmp")

    def test_state_accepts_repo_before_the_subcommand(self):
        args = fps_state.build_parser().parse_args(["--repo", "/tmp", "list"])
        self.assertEqual(args.repo, "/tmp")


class BindingRefusalTests(unittest.TestCase):
    """The session binding is enforced at the process boundary, not just in a function."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.bound = str(Path(self._tmp.name) / "bound")
        self.other = str(Path(self._tmp.name) / "other")
        Path(self.bound).mkdir(parents=True)
        Path(self.other).mkdir(parents=True)
        self.env = dict(os.environ,
                        FPS_HOME=str(Path(self._tmp.name) / "fpshome"),
                        FPS_BOUND_REPO=self.bound)

    def tearDown(self):
        self._tmp.cleanup()

    def run_services(self, *argv):
        return subprocess.run([sys.executable, str(SCRIPTS / "fps_services.py"), *argv], check=False,
                              capture_output=True, text=True, env=self.env, timeout=30)

    def test_a_conflicting_repo_is_refused(self):
        p = self.run_services("notices", "--repo", self.other)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("bound to", p.stderr)

    def test_the_bound_repo_is_accepted(self):
        p = self.run_services("notices", "--repo", self.bound)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_no_repo_argument_uses_the_binding(self):
        p = self.run_services("notices")
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_the_refusal_says_how_to_proceed(self):
        p = self.run_services("notices", "--repo", self.other)
        self.assertIn("new one", p.stderr.lower())

    def test_open_loops_honour_the_same_binding(self):
        p = subprocess.run([sys.executable, str(SCRIPTS / "fps_state.py"), "list", "--repo", self.other], check=False,
                           capture_output=True, text=True, env=self.env, timeout=30)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("bound to", p.stderr)


if __name__ == "__main__":
    unittest.main()
