"""install.sh wires this clone into ~/.local/bin; every shim it writes must run.

A shim is a two-line script that execs a path inside the clone. When that path
moves or leaves the repo, install.sh still writes the shim and exits 0, and the
command only fails the next time someone types it.
"""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class InstallShimsResolve(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self.home = Path(self._home.name)
        env = {**os.environ, "HOME": str(self.home)}
        subprocess.run(["bash", str(ROOT / "install.sh")], env=env, check=True,
                       capture_output=True)
        self.shims = sorted((self.home / ".local/bin").iterdir())

    def tearDown(self):
        self._home.cleanup()

    def test_install_writes_shims(self):
        self.assertTrue(self.shims, "install.sh wrote no shims")

    def test_every_shim_execs_a_file_inside_this_clone(self):
        broken = []
        for shim in self.shims:
            target = re.search(r'exec (?:python3 )?"([^"]+)"', shim.read_text()).group(1)
            if not Path(target).is_file():
                broken.append(f"{shim.name} -> {target}")
        self.assertEqual(broken, [], f"shims pointing at nothing: {broken}")


if __name__ == "__main__":
    unittest.main()
