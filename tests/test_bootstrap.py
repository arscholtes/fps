"""Learning a repo well enough to write down how to work in it."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fps_bootstrap as fb


class RepoFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, body=""):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        return p


class LanguageTests(RepoFixture):
    def test_a_gemfile_means_ruby(self):
        self.write("Gemfile", "source 'https://rubygems.org'")
        self.assertEqual(fb.detect_language(self.repo)["language"], "ruby")

    def test_rails_is_recognised_beyond_plain_ruby(self):
        self.write("Gemfile", "gem 'rails', '~> 7.2'")
        self.write("config/application.rb", "")
        self.assertEqual(fb.detect_language(self.repo)["framework"], "rails")

    def test_a_package_json_means_node(self):
        self.write("package.json", '{"name":"x"}')
        self.assertEqual(fb.detect_language(self.repo)["language"], "node")

    def test_python_is_detected_from_layout_alone(self):
        self.write("thing/__init__.py")
        self.write("thing/cli.py")
        self.assertEqual(fb.detect_language(self.repo)["language"], "python")

    def test_an_empty_directory_is_unknown_not_a_guess(self):
        self.assertEqual(fb.detect_language(self.repo)["language"], "unknown")

    def test_ruby_wins_over_a_stray_python_file(self):
        self.write("Gemfile", "")
        self.write("script.py", "")
        self.assertEqual(fb.detect_language(self.repo)["language"], "ruby")


class CommandTests(RepoFixture):
    def test_python_with_a_tests_dir_gets_a_unittest_command(self):
        self.write("thing/__init__.py")
        self.write("tests/test_x.py")
        cmds = fb.detect_commands(self.repo, fb.detect_language(self.repo))
        self.assertIn("unittest", cmds["test"])

    def test_a_repo_with_no_tests_reports_no_test_command(self):
        self.write("thing/__init__.py")
        self.assertIsNone(fb.detect_commands(self.repo, fb.detect_language(self.repo))["test"])

    def test_rspec_is_found_from_the_spec_directory(self):
        self.write("Gemfile", "")
        self.write("spec/models/a_spec.rb", "")
        cmds = fb.detect_commands(self.repo, fb.detect_language(self.repo))
        self.assertIn("rspec", cmds["test"])

    def test_a_node_test_script_is_read_from_package_json(self):
        self.write("package.json", '{"scripts":{"test":"vitest run"}}')
        cmds = fb.detect_commands(self.repo, fb.detect_language(self.repo))
        self.assertIn("npm test", cmds["test"])

    def test_a_corrupt_package_json_does_not_crash_detection(self):
        self.write("package.json", "{ not json")
        self.assertIsNone(fb.detect_commands(self.repo, fb.detect_language(self.repo))["test"])


class LayoutTests(RepoFixture):
    def test_top_level_directories_are_reported(self):
        self.write("app/models/a.rb")
        self.write("lib/b.rb")
        names = [d["name"] for d in fb.detect_layout(self.repo)]
        self.assertIn("app", names)
        self.assertIn("lib", names)

    def test_dot_directories_are_not_reported_as_layout(self):
        (self.repo / ".git").mkdir()
        self.assertNotIn(".git", [d["name"] for d in fb.detect_layout(self.repo)])

    def test_layout_entries_carry_a_file_count(self):
        self.write("lib/a.rb")
        self.write("lib/b.rb")
        entry = next(d for d in fb.detect_layout(self.repo) if d["name"] == "lib")
        self.assertEqual(entry["files"], 2)


class PromiseTests(RepoFixture):
    def test_a_stdlib_only_readme_is_recorded_as_a_promise(self):
        self.write("README.md", "This is stdlib only, no dependencies.")
        self.assertTrue(fb.detect_promises(self.repo))

    def test_a_readme_without_a_promise_records_none(self):
        self.write("README.md", "A tool for doing things.")
        self.assertEqual(fb.detect_promises(self.repo), [])

    def test_a_missing_readme_records_none(self):
        self.assertEqual(fb.detect_promises(self.repo), [])


class RenderTests(RepoFixture):
    def setUp(self):
        super().setUp()
        self.write("thing/__init__.py")
        self.write("thing/cli.py")
        self.write("tests/test_a.py")
        self.write("README.md", "stdlib only, no dependencies")

    def test_the_draft_names_the_repo(self):
        self.assertIn(self.repo.name, fb.render(fb.learn(self.repo)))

    def test_the_draft_carries_the_test_command(self):
        self.assertIn("unittest", fb.render(fb.learn(self.repo)))

    def test_the_draft_defers_to_the_global_rules_rather_than_repeating_them(self):
        self.assertIn("~/.claude/CLAUDE.md", fb.render(fb.learn(self.repo)))

    def test_the_draft_records_the_dependency_promise(self):
        self.assertIn("stdlib", fb.render(fb.learn(self.repo)).lower())

    def test_writing_never_overwrites_an_existing_claude_md(self):
        existing = self.write("CLAUDE.md", "hand written, do not clobber")
        fb.write_out(self.repo, fb.learn(self.repo), write_repo_file=True)
        self.assertEqual(existing.read_text(), "hand written, do not clobber")

    def test_writing_creates_the_file_when_absent(self):
        fb.write_out(self.repo, fb.learn(self.repo), write_repo_file=True)
        self.assertTrue((self.repo / "CLAUDE.md").exists())


if __name__ == "__main__":
    unittest.main()
