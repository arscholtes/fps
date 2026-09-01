"""The claims these scripts make, turned into checks.

fps_services says it is "deliberately read-only about services: it reports, it
does not restart anything", and the reason is stated right there — something that
silently restarts a server you were mid-debug on is worse than something that
tells you the server is down. That is a promise about what the code may do, so
only reading the code can falsify it.
"""

import ast
import subprocess
import sys
import unittest
from pathlib import Path

import fps_services

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

# Commands that change the state of a running system. Reporting needs none of them.
MUTATING = {
    "restart", "start", "stop", "kill", "killall", "pkill", "reboot",
    "systemctl", "launchctl", "brew", "rm", "mv", "chmod", "chown",
    "docker-compose", "supervisorctl", "service",
}
# Read-only invocations fps_services legitimately makes.
READ_ONLY_BINARIES = {"docker", "ps", "lsof", "git", "python3", "sqlite3", "osascript"}
DOCKER_READ_ONLY = {"ps", "inspect", "logs", "stats", "version", "info"}


# Only calls that actually execute something. Reading every list of strings in
# the file instead picks up ("error", "...") tuples appended to a report and
# reads them as commands.
EXECUTORS = {"run", "call", "check_call", "check_output", "Popen", "getoutput"}


def literal_command_lists(tree):
    """@return [Array<Array<String>>] argv lists passed to something that executes."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        label = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if label not in EXECUTORS:
            continue
        for arg in node.args:
            if isinstance(arg, (ast.List, ast.Tuple)):
                parts = [e.value for e in arg.elts
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if parts:
                    out.append(parts)
    return out


class ReadOnlyAboutServicesTests(unittest.TestCase):
    def setUp(self):
        self.src = (SCRIPTS / "fps_services.py").read_text()
        self.tree = ast.parse(self.src)

    def test_no_mutating_command_is_invoked(self):
        offenders = []
        for cmd in literal_command_lists(self.tree):
            head = Path(cmd[0]).name
            if head in MUTATING:
                offenders.append(" ".join(cmd))
        self.assertEqual(offenders, [], "a command that changes running state")

    def test_docker_is_only_ever_asked_to_report(self):
        for cmd in literal_command_lists(self.tree):
            if Path(cmd[0]).name != "docker":
                continue
            self.assertIn(cmd[1], DOCKER_READ_ONLY,
                          f"docker {cmd[1]} is not a reporting command")

    def test_every_binary_it_shells_out_to_is_a_reporting_tool(self):
        for cmd in literal_command_lists(self.tree):
            head = Path(cmd[0]).name
            self.assertIn(head, READ_ONLY_BINARIES,
                          f"{head} is not in the read-only set")

    def test_it_never_uses_a_shell(self):
        # shell=True would put an arbitrary command line outside every check above.
        self.assertNotIn("shell=True", self.src)

    def test_the_only_writes_are_to_its_own_database(self):
        # Notices and open loops are its own state; nothing else may be written.
        offenders = []
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "open"
                    and len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
                    and ("w" in str(node.args[1].value) or "a" in str(node.args[1].value))):
                offenders.append(ast.unparse(node))
        self.assertEqual(offenders, [])


class ReportingStaysReportingTests(unittest.TestCase):
    def test_problems_reports_without_repairing(self):
        """Checked against the parse tree, not the text.

        A substring search for "restart" matches `"restarting" in status`, which
        is reading a container's reported state — the same substring-versus-
        semantics trap that made ".git" match ".github" elsewhere in this stack.
        """
        src = (SCRIPTS / "fps_services.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name == "find_problems")
        for cmd in literal_command_lists(fn):
            self.assertNotIn(Path(cmd[0]).name, MUTATING)
        self.assertTrue(callable(fps_services.find_problems))

    def test_the_status_command_exits_without_touching_anything(self):
        p = subprocess.run([sys.executable, str(SCRIPTS / "fps_services.py"), "sessions"], check=False,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
