#!/usr/bin/env python3
"""Place FPS windows across the attached displays.

The placement itself is a pure function — screens and windows in, rectangles out —
so the multi-monitor case is testable on a single-monitor machine. Only `apply`
touches anything real.

Screen desirability defaults to main-first, then largest. A window's priority is
its attention rank; the highest-attention window gets the most desirable screen.
"""
import subprocess
import sys
from pathlib import Path

INSET = 8
PROBE = Path(__file__).resolve().parent / "fps-layout.swift"


def screens():
    """@return [list<dict>] displays in AppleScript coordinates."""
    out = subprocess.run(["swift", str(PROBE)], capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.strip().splitlines():
        i, x, y, w, h, flag = line.split("\t")
        rows.append({"idx": int(i), "x": int(x), "y": int(y),
                     "w": int(w), "h": int(h), "main": flag == "MAIN"})
    return rows


def rank_screens(scr, prefer="main"):
    """Most desirable first. `prefer` is 'main' or 'largest'."""
    if prefer == "largest":
        return sorted(scr, key=lambda s: (-(s["w"] * s["h"]), not s["main"]))
    return sorted(scr, key=lambda s: (not s["main"], -(s["w"] * s["h"])))


def layout(scr, windows, prefer="main", inset=INSET):
    """Zip window priority against screen desirability.

    @param windows [list] window ids, highest attention first
    @return [list<tuple>] (window_id, left, top, right, bottom)
    """
    ranked = rank_screens(scr, prefer)
    if not ranked:
        return []
    out = []
    for n, win in enumerate(windows):
        s = ranked[min(n, len(ranked) - 1)]  # extras stack on the least desirable
        out.append((win, s["x"] + inset, s["y"] + inset,
                    s["x"] + s["w"] - inset, s["y"] + s["h"] - inset))
    return out


# Pilot is the backbone of FPS and does not compete for its slot. This is a hard
# constraint rather than a ranking output: no combination of screen size or
# main-ness may move it.
CENTRE_ROLE = "pilot"


def centre_screen(scr):
    """The screen nearest the middle of the whole desktop.

    macOS MAIN and the physically central display are different things, and on
    this desk they are different screens: the desktop spans x=-2560 to 2056, so
    the physical centre is x=-252, which falls on the external — while the
    built-in is MAIN. "Front and centre" reads either way, so both are offered.

    @return [Hash, nil]
    """
    if not scr:
        return None
    left = min(s["x"] for s in scr)
    right = max(s["x"] + s["w"] for s in scr)
    middle = (left + right) / 2
    return min(scr, key=lambda s: abs((s["x"] + s["w"] / 2) - middle))


def _pilot_screen(scr, centre):
    if centre == "physical":
        return centre_screen(scr)
    return next((s for s in scr if s.get("main")), scr[0])


def arrange(scr, roles, centre="main"):
    """Assign each role a screen, symmetrically around pilot.

    Symmetry around a centre wants an ODD screen count: with three screens and
    five roles it is 2 | pilot | 2, which is the arrangement he described. With an
    EVEN count there is no symmetric answer, so rather than letting the ranking
    decide silently, pilot takes one screen alone and everything else shares the
    other — the closest thing to symmetry an even count allows, and stated.

    @param scr [list<dict>] screens
    @param roles [list<str>] role names
    @param centre [str] 'main' (default) or 'physical'
    @return [dict] role -> screen
    """
    if not scr or not roles:
        return {}

    pilot_scr = _pilot_screen(scr, centre)
    others = [r for r in roles if r != CENTRE_ROLE]
    placed = {}
    if CENTRE_ROLE in roles:
        placed[CENTRE_ROLE] = pilot_scr

    flanks = [s for s in scr if s is not pilot_scr]
    if not flanks:
        # One screen: everything shares it. Still better than refusing.
        for r in others:
            placed[r] = pilot_scr
        return placed

    # Left and right of pilot, so the split is visible on the desk rather than
    # merely balanced in count.
    left = sorted([s for s in flanks if s["x"] < pilot_scr["x"]], key=lambda s: -s["x"])
    right = sorted([s for s in flanks if s["x"] >= pilot_scr["x"]], key=lambda s: s["x"])
    sides = []
    while left or right:
        if left:
            sides.append(left.pop(0))
        if right:
            sides.append(right.pop(0))

    for n, role in enumerate(others):
        placed[role] = sides[n % len(sides)]
    return placed


def rects(placed, inset=INSET):
    """@return [list<tuple>] (role, left, top, right, bottom), negatives intact."""
    out = []
    for role, s in placed.items():
        out.append((role, s["x"] + inset, s["y"] + inset,
                    s["x"] + s["w"] - inset, s["y"] + s["h"] - inset))
    return out


def apply(rects):
    """Move existing windows. Never creates or closes one — sessions stay live."""
    lines = ['tell application "iTerm2"']
    for win, left, top, right, bottom in rects:
        lines.append(f"  set bounds of window {win} to {{{left}, {top}, {right}, {bottom}}}")
    lines.append("end tell")
    subprocess.run(["osascript", "-e", "\n".join(lines)], check=True)


if __name__ == "__main__":
    prefer = "largest" if "--largest" in sys.argv else "main"
    scr = screens()
    wins = list(range(1, int(sys.argv[1]) + 1)) if sys.argv[1:] and sys.argv[1].isdigit() else [1, 2]
    plan = layout(scr, wins, prefer)
    for win, left, top, right, bottom in plan:
        s = next(s for s in rank_screens(scr, prefer) if s["x"] <= left < s["x"] + s["w"])
        print(f"  window {win} → display {s['idx']}{' MAIN' if s['main'] else ''}  "
              f"{right-left}x{bottom-top} at ({left},{top})")
    if "--apply" in sys.argv:
        apply(plan)
        print("  applied — sessions untouched")
