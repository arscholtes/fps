"""Employer identifiers stay out of code and config.

Alex left that employer at the end of August 2026. What remained was not mainly a
privacy problem, it was broken configuration: the standup's git-evidence repo and
its calendar id both still named the employer, so evidence lookups ran against a
checkout with no recent commits of his and returned "no commits in window" forever
— indistinguishable from an honestly idle block.

`debates/` is deliberately exempt. Those are evidence documents and the mentions
are load-bearing: `workrepo-82594993.db` is a real filename and "26 unread notices
in workrepo" is a measurement. Genericising them would damage the record to no
benefit while the repo is private. That exemption is a decision, not an oversight.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FORBIDDEN = re.compile(r"workrepo|LIF-\d", re.I)
# Everything tracked except the transcripts and this file.
SEARCH = ("scripts/*.py", "tests/*.py", "*.toml", "*.md",
          "skills/**/*.py", "skills/**/*.md", "skills/**/*.rb", "skills/**/*.toml",
          "skills/**/*.json", "skills/**/*.yml")


class NoEmployerIdentifiersOutsideTheTranscripts(unittest.TestCase):
    def test_code_and_config_name_no_employer(self):
        here = pathlib.Path(__file__).name
        offenders = []
        for pattern in SEARCH:
            for path in ROOT.glob(pattern):
                if path.name == here or "debates" in path.parts:
                    continue
                for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                    if FORBIDDEN.search(line):
                        offenders.append(f"{path.relative_to(ROOT)}:{n}")
        self.assertEqual(offenders, [], f"employer identifier reintroduced: {offenders}")


if __name__ == "__main__":
    unittest.main()
