"""A former employer's name stays out of every tracked file.

The name is held only as a SHA-256 digest, so this guard can run in the public
repo without spelling out what it guards against. Every word in every tracked
text file is lowercased, hashed and compared with the digest; ticket ids are
the name's three-letter prefix followed by a number.

`debates/` is exempt: the transcripts are evidence documents whose mentions are
load-bearing, and they never leave the private repo — publishing strips them.
"""
import hashlib
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = {"96de81af4ea263b8eecadb279fe7c45221d25eb4771f07a902d7de759e62cd74"}
TICKET_PREFIX = hashlib.sha256(b"lif").hexdigest()
WORD = re.compile(r"[a-z0-9]+")
EXEMPT = ("debates/",)


def _digest(word):
    """@return [str] hex SHA-256 of the word"""
    return hashlib.sha256(word.encode()).hexdigest()


def offending_lines(text):
    """@param text [str] file contents
    @return [list[int]] 1-based numbers of lines naming the employer or one of its tickets
    """
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        words = WORD.findall(line.lower())
        digests = [_digest(w) for w in words]
        ticket = any(d == TICKET_PREFIX and nxt.isdigit() for d, nxt in zip(digests, words[1:], strict=False))
        if ticket or FORBIDDEN.intersection(digests):
            hits.append(n)
    return hits


class NoEmployerIdentifiers(unittest.TestCase):
    def test_no_tracked_file_names_the_employer(self):
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True,
                                 capture_output=True, text=True).stdout.split("\0")
        offenders = []
        for rel in filter(None, tracked):
            if rel.startswith(EXEMPT):
                continue
            try:
                text = (ROOT / rel).read_text()
            except UnicodeDecodeError:
                continue  # binary file
            offenders += [f"{rel}:{n}" for n in offending_lines(text)]
        self.assertEqual(offenders, [], f"employer identifier reintroduced: {offenders}")

    def test_a_forbidden_word_is_caught_in_any_case_and_inside_a_path(self):
        with mock.patch.dict(globals(), FORBIDDEN={_digest("zebra")}):
            self.assertEqual(offending_lines("ok\nsee Zebra-Dev/skills\n"), [2])
            self.assertEqual(offending_lines("zebras and a zebrafish"), [])

    def test_a_ticket_id_is_caught_and_the_bare_prefix_is_not(self):
        with mock.patch.dict(globals(), TICKET_PREFIX=_digest("zeb")):
            self.assertEqual(offending_lines("fixes ZEB-1234"), [1])
            self.assertEqual(offending_lines("zeb alone, zebu and zeb-a are fine"), [])


if __name__ == "__main__":
    unittest.main()
