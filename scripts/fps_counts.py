#!/usr/bin/env python3
"""Per-role green/red counts: what each node can do, and what it needs from Alex.

GREEN is claimable work — `bd ready` filtered to a role label. It drains itself:
a node picks work up and the number falls.

RED is blocked on a human — open gates and unresolved loops. It only ever drains
when Alex acts, so it is the half that silently accumulates and the only half
that should make him look at the line.

Both numbers are enumerable through `fps-blocked`. A count with no way to see
what it counts becomes wallpaper, which is the shape that produced 80 unread
notices and 4 stale loops before anyone noticed.

The pure functions here take already-fetched data so they are testable without
beads or a database; the fetchers are separate and live at the bottom.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROLES = ("forge", "pilot", "shepherd", "warden", "mentor")
STALE_AFTER = 60.0
BD_TIMEOUT = 5.0
SNAPSHOT_DIR = Path("~/.local/share/fps").expanduser()


def system_path():
    """The aggregate every terminal reads. Identical everywhere, by design."""
    return SNAPSHOT_DIR / "counts-system.json"


def merge(snapshots):
    """Sum per-repo snapshots into one view of the whole system.

    A dot answers "what does this node have", which is a question about the node
    rather than about a checkout. Per-repo counts rendered blank in the terminal
    Alex actually sits in, because beads is empty in the repo his sessions bind
    to while the work lives in two others.

    Items keep their repo, so the enumerable list still says where to go.

    @param snapshots [Array<Hash>] per-repo snapshots
    @return [Hash] the same shape, summed
    """
    roles = {r: {"green": 0, "red": 0} for r in ROLES}
    items, unattributed = [], 0
    for snap in snapshots:
        for role, counts in (snap.get("roles") or {}).items():
            if role in roles:
                roles[role]["green"] += counts.get("green", 0)
                roles[role]["red"] += counts.get("red", 0)
        unattributed += snap.get("unattributed", 0)
        where = Path(snap["repo"]).name if snap.get("repo") else "?"
        items += [{**item, "repo": item.get("repo") or where}
                  for item in (snap.get("items") or [])]
    return {"roles": roles, "unattributed": unattributed, "items": items,
            "generated_at": datetime.now(timezone.utc).isoformat()}


def snapshot_path(repo):
    """One snapshot per repo. Beads is per-repo, so a single shared file would
    show a workrepo terminal the counts from fps.

    @param repo [String] repo path
    @return [String] path to that repo's snapshot
    """
    tenant = _tenant()
    slug = tenant.slug_for(repo) if tenant else Path(repo).resolve().name
    return SNAPSHOT_DIR / f"counts-{slug}.json"


def green_counts(ready):
    """Claimable work per role.

    Work with no role label counts for nobody rather than for everybody — the
    notices count already makes the opposite choice and it is why the status
    line and the CLI can disagree.

    @param ready [Array<Hash>] issues from `bd ready --json`
    @return [Hash] every role, including the ones with nothing
    """
    out = dict.fromkeys(ROLES, 0)
    for issue in ready or []:
        for label in issue.get("labels") or []:
            if label in out:
                out[label] += 1
    return out


def red_items(gates, loops):
    """Everything waiting on a human, as a list rather than a number.

    A gate belongs to the role whose work it blocks. One that blocks unlabelled
    work is attributed to nobody and reported separately — dropping it would
    make the dots disagree with the list.

    @param gates [Array<Hash>] gate issues, each with a `blocks` list
    @param loops [Array<Hash>] rows from open_loops
    @return [Array<Hash>] {id, kind, role, what}
    """
    items = []
    for gate in gates or []:
        if (gate.get("status") or "").lower() != "open":
            continue
        role = None
        for blocked in gate.get("blocks") or []:
            role = next((x for x in (blocked.get("labels") or []) if x in ROLES), None)
            if role:
                break
        blocked_ids = ", ".join(b.get("id", "?") for b in gate.get("blocks") or []) or "nothing"
        items.append({"id": gate.get("id"), "kind": "gate", "role": role,
                      "what": f"{gate.get('title') or 'gate'} — blocks {blocked_ids}"})

    for loop in loops or []:
        if loop.get("resolved_at"):
            continue
        asked = loop.get("asked_of") or "someone"
        items.append({"id": f"loop-{loop.get('id')}", "kind": "loop", "role": None,
                      "what": f"asked of {asked}: {(loop.get('question') or '').strip()[:70]}"})
    return items


def snapshot(ready, gates, loops):
    """The whole system in one object, as the status line renders it.

    @return [Hash] {roles: {role: {green, red}}, unattributed, items, generated_at}
    """
    green = green_counts(ready)
    items = red_items(gates, loops)
    roles = {r: {"green": green[r], "red": 0} for r in ROLES}
    unattributed = 0
    for item in items:
        if item["role"] in roles:
            roles[item["role"]]["red"] += 1
        else:
            unattributed += 1
    return {"roles": roles, "unattributed": unattributed, "items": items,
            "generated_at": datetime.now(timezone.utc).isoformat()}


# --------------------------------------------------------------------- fetching

class BeadsUnavailable(RuntimeError):
    """bd could not be run. Distinct from "bd ran and found nothing"."""


def _bd(repo, *args):
    try:
        p = subprocess.run(["bd", *args, "--json"], cwd=repo, capture_output=True,
                           text=True, timeout=BD_TIMEOUT, check=False)
        return json.loads(p.stdout) if p.stdout.strip() else []
    except FileNotFoundError as exc:
        # A missing bd must not read as an empty queue. The 15s writer runs under
        # launchd with a minimal PATH, where this silently produced all-zero
        # counts that looked exactly like a quiet system.
        raise BeadsUnavailable(f"bd not found on PATH ({exc})") from exc
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []


def fetch(repo):
    """Read the live state for one repo. Slow enough to belong in the writer, not the render."""
    ready = _bd(repo, "ready")
    listed = _bd(repo, "list", "--include-gates")
    listed = listed if isinstance(listed, list) else listed.get("issues", [])
    by_id = {i.get("id"): i for i in listed}

    gates = []
    for issue in listed:
        if issue.get("issue_type") != "gate":
            continue
        blocks = [{"id": i.get("id"), "labels": i.get("labels")}
                  for i in listed
                  if any(d == issue.get("id") for d in (i.get("dependencies") or []))]
        if not blocks:
            blocks = _blocks_via_show(repo, issue.get("id"), by_id)
        gates.append({**issue, "blocks": blocks})
    return ready if isinstance(ready, list) else [], gates, _loops(repo)


def _blocks_via_show(repo, gate_id, by_id):
    """`bd list` does not carry the reverse edge; `bd show` prints it."""
    try:
        p = subprocess.run(["bd", "show", gate_id], cwd=repo, capture_output=True,
                           text=True, timeout=BD_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    out, seen = [], False
    for line in p.stdout.splitlines():
        if line.strip().startswith("BLOCKS"):
            seen = True
            continue
        if seen:
            for token in line.replace("←", " ").replace("○", " ").split():
                key = token.rstrip(":")
                if key in by_id:
                    out.append({"id": key, "labels": by_id[key].get("labels")})
            if line.strip() and not line.startswith(" "):
                break
    return out


def _loops(repo):
    tenant = _tenant()
    if not tenant:
        return []
    try:
        conn = tenant.connect_tenant(repo)
        cols = [c[1] for c in conn.execute("pragma table_info(open_loops)")]
        if not cols:
            return []
        rows = conn.execute("select * from open_loops")
        return [dict(zip(cols, row, strict=False)) for row in rows]
    except Exception:
        return []


def _tenant():
    for d in ("~/Developer/fps/scripts", "~/.claude/skills/fps/scripts"):
        path = Path(d).expanduser()
        if (path / "fps_tenant.py").exists():
            if path not in sys.path:
                sys.path.insert(0, path)
            try:
                import fps_tenant
            except ImportError:
                return None
            return fps_tenant
    return None


def write_snapshot(repo, path=None):
    """Fetch and persist. Called by the 15s writer, never by the status line."""
    path = path or snapshot_path(repo)
    ready, gates, loops = fetch(repo)
    snap = snapshot(ready, gates, loops)
    snap["repo"] = repo
    _write_json(path, snap)
    return snap


def _write_json(path, payload):
    """Atomic write: a reader never sees a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as fh:
        json.dump(payload, fh)
    tmp.replace(path)


def read_snapshot(path=None):
    """@return [Hash, nil] the system-wide snapshot, or None if never written."""
    if path is None:
        path = system_path()
    try:
        with Path(path).open() as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def age_seconds(snap):
    """@return [Float, nil] how stale the snapshot is, so nothing presents it as live."""
    try:
        then = datetime.fromisoformat(snap["generated_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds()


# ------------------------------------------------------------------------- cli

def _render_list(snap, role=None):
    """What the red digit counts, as text. The dots are only honest if this exists."""
    items = snap.get("items") or []
    if role:
        items = [i for i in items if i.get("role") == role]
    lines = []
    age = age_seconds(snap)
    if age is not None and age > STALE_AFTER:
        lines.append(f"counts are {int(age)}s old — the writer may not be running\n")
    if not items:
        lines.append(f"nothing is waiting on you for {role}." if role
                     else "nothing is waiting on you.")
        return "\n".join(lines)

    for scope in [*ROLES, None]:
        group = [i for i in items if i.get("role") == scope]
        if not group:
            continue
        lines.append(f"{scope or 'unattributed — not labelled for any role'}")
        for item in group:
            lines.append(f"  {item['id']:<12}{item['kind']:<7}{item['what']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    repo = os.environ.get("FPS_BOUND_REPO") or str(Path.cwd())

    if argv and argv[0] == "--write-all":
        # Every joined repo, then one aggregate every terminal reads. Beads
        # state is per-repo, but a node's queue is not: what a role can pick up
        # is the same question wherever the terminal happens to be bound.
        tenant = _tenant()
        repos = [r.get("path") for r in tenant.list_repos()] if tenant else [repo]
        snaps = []
        for r in [x for x in repos if x and Path(x).is_dir()]:
            snaps.append(write_snapshot(r))
        system = merge(snaps)
        _write_json(system_path(), system)
        print("system  " + "  ".join(f"{k}{v['green']}/{v['red']}"
                                     for k, v in system["roles"].items()
                                     if v["green"] or v["red"])
              + (f"  unattributed={system['unattributed']}" if system["unattributed"] else "")
              + f"  ({len(snaps)} repos)")
        return 0

    if argv and argv[0] == "--write":
        snap = write_snapshot(repo)
        print(f"wrote {snapshot_path(repo)}: "
              + "  ".join(f"{r}{v['green']}/{v['red']}" for r, v in snap["roles"].items())
              + f"  unattributed={snap['unattributed']}")
        return 0

    snap = read_snapshot()
    if snap is None:
        snap = write_snapshot(repo)      # first run, or the writer is not loaded yet
    role = argv[0] if argv and argv[0] in ROLES else None
    print(_render_list(snap, role))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
