"""FPS runs the same five roles under either agent, so it has to see both.

Liveness is asked of the process, not of an agent's session store, because a
record outlives the thing it describes and a pid that answers does not. The
parsing is tested here; the process listing is not, because asserting on a live
machine's `ps` output tests the machine.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fps_services  # noqa: E402


class HermesProfileFromACommandLine(unittest.TestCase):
    def test_the_wrapper_shape_fps_tab_execs(self):
        line = "/Users/a/.hermes/hermes-agent/venv/bin/python /Users/a/.hermes/hermes-agent/hermes -p forge"
        self.assertEqual(fps_services.hermes_profile(line), "forge")

    def test_a_bare_invocation(self):
        self.assertEqual(fps_services.hermes_profile("hermes -p mentor chat"), "mentor")

    def test_hermes_without_a_profile_is_not_a_role_session(self):
        self.assertIsNone(fps_services.hermes_profile("/usr/local/bin/hermes sessions list"))

    def test_something_else_entirely(self):
        self.assertIsNone(fps_services.hermes_profile("claude --name forge"))
        self.assertIsNone(fps_services.hermes_profile("vim -p notes.md"))

    def test_a_path_that_merely_contains_the_word(self):
        # "-p" belongs to grep here, and the binary is not hermes.
        self.assertIsNone(fps_services.hermes_profile("grep -p hermes /var/log/system.log"))


if __name__ == "__main__":
    unittest.main()
