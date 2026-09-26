#!/usr/bin/env bash
# qa-gate — one PASS/FAIL verdict for the repo in $PWD (or $1).
#
# Language-agnostic: detects the project type rather than assuming one. Every
# check prints its own verdict; the exit code is the gate. Nothing is repaired
# here — a gate that fixes what it finds cannot be trusted to report.
#
#   qa-gate.sh [repo]        run every applicable check
#   qa-gate.sh --list        show what would run, and skip nothing quietly
#   qa-gate.sh --only NAME   run one check (tests|lint|secrets|gitignore|smoke|promise)
#
# Exit 0 = PASS, 1 = FAIL, 2 = could not run.

set -uo pipefail

LIST=0
ONLY=""
REPO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --list)   LIST=1 ;;
    --only)   ONLY="${2:-}"; shift ;;
    --only=*) ONLY="${1#--only=}" ;;
    *)        [ -n "$REPO" ] || REPO="$1" ;;
  esac
  shift
done
[ -n "$REPO" ] || REPO="$PWD"
cd "$REPO" 2>/dev/null || { echo "qa-gate: no such directory: $REPO" >&2; exit 2; }
REPO="$(pwd -P)"

FAILED=0
declare -a RESULTS

record() { # verdict, name, detail
  RESULTS+=("$1|$2|$3")
  [ "$1" = "FAIL" ] && FAILED=1
  return 0
}

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- interpreter
# Bare `python3` is whatever PATH happens to name, and on macOS a minimal PATH
# names /usr/bin/python3, which is 3.9.6 and has no tomllib. Measured 2026-09-07:
# the gate PASSED jobhunt from an interactive shell and every test importing
# jobhunt.resume fails under the same gate from a hook, because homebrew sorts
# first in one and not the other. A gate whose verdict depends on the caller's
# PATH is not a gate.
#
# So it is resolved once, newest first, and printed with the verdict. A PASS that
# does not say which interpreter produced it cannot be checked.
PY3=""
for cand in "${QA_GATE_PYTHON:-}" /opt/homebrew/bin/python3 /usr/local/bin/python3 \
            "$(command -v python3 2>/dev/null)" /usr/bin/python3; do
  [ -n "$cand" ] && [ -x "$cand" ] || continue
  ver=$("$cand" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null) || continue
  PY3="$cand"; PY3_VER="$ver"
  break
done

# ---------------------------------------------------------------- detection
KIND="unknown"
if   [ -f "$REPO/Gemfile" ];        then KIND="ruby"
elif [ -f "$REPO/package.json" ];   then KIND="node"
elif [ -f "$REPO/Package.swift" ] || compgen -G "$REPO/*.xcodeproj" >/dev/null 2>&1; then KIND="swift"
elif compgen -G "$REPO/*/*.py" >/dev/null 2>&1 || compgen -G "$REPO/*.py" >/dev/null 2>&1; then KIND="python"
fi

if [ "$LIST" = "1" ]; then
  echo "repo: $REPO"
  echo "kind: $KIND"
  echo "checks: tests, lint, secrets, gitignore, smoke, dependency-promise"
  exit 0
fi

# ---------------------------------------------------------------- 1. tests
run_tests() {
  case "$KIND" in
    python)
      if [ -d "$REPO/tests" ]; then
        out=$("$PY3" -m unittest discover -s tests 2>&1); rc=$?
      else
        record SKIP tests "no tests/ directory — nothing verifies this repo"; return
      fi ;;
    ruby)
      if [ -d "$REPO/spec" ]; then out=$(bundle exec rspec 2>&1); rc=$?
      else record SKIP tests "no spec/ directory"; return; fi ;;
    node)
      if grep -q '"test"' package.json 2>/dev/null; then out=$(npm test --silent 2>&1); rc=$?
      else record SKIP tests "no test script in package.json"; return; fi ;;
    swift)
      if [ -f "$REPO/Package.swift" ]; then out=$(swift test 2>&1); rc=$?
      else record SKIP tests "no Package.swift"; return; fi ;;
    *) record SKIP tests "unknown project type"; return ;;
  esac
  if [ "$rc" -eq 0 ]; then record PASS tests "suite green"
  else record FAIL tests "$(printf '%s' "$out" | tail -20)"; fi
}

# ---------------------------------------------------------------- 2. lint
run_lint() {
  case "$KIND" in
    python)
      if have ruff; then out=$(ruff check . 2>&1); rc=$?
      else
        # No linter installed is not a pass. Syntax at least must hold.
        out=$("$PY3" -m compileall -q . 2>&1); rc=$?
        [ "$rc" -eq 0 ] && { record PASS lint "no linter configured; syntax clean"; return; }
      fi ;;
    ruby)  have rubocop && { out=$(bundle exec rubocop 2>&1); rc=$?; } || { record SKIP lint "rubocop not installed"; return; } ;;
    node)  grep -q '"lint"' package.json 2>/dev/null && { out=$(npm run lint --silent 2>&1); rc=$?; } || { record SKIP lint "no lint script"; return; } ;;
    swift) have swiftlint && { out=$(swiftlint 2>&1); rc=$?; } || { record SKIP lint "swiftlint not installed"; return; } ;;
    *) record SKIP lint "unknown project type"; return ;;
  esac
  if [ "$rc" -eq 0 ]; then record PASS lint "clean"
  else record FAIL lint "$(printf '%s' "$out" | tail -15)"; fi
}

# ---------------------------------------------------------------- 3. secrets
run_secrets() {
  # Tracked and staged content only — the gate cannot see what git will not carry.
  files=$(git -C "$REPO" ls-files 2>/dev/null)
  [ -z "$files" ] && { record SKIP secrets "not a git repo"; return; }
  hits=$(printf '%s\n' "$files" | while read -r f; do
    [ -f "$REPO/$f" ] || continue
    printf '%s' "$f" | grep -qE '\.(example|sample|md|lock)$' && continue
    grep -nEI '(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)' "$REPO/$f" 2>/dev/null \
      | sed "s|^|$f:|" | cut -c1-120
  done)
  if [ -z "$hits" ]; then record PASS secrets "no credential patterns in tracked files"
  else record FAIL secrets "$hits"; fi
}

# ---------------------------------------------------------------- 4. gitignore
run_gitignore() {
  [ -d "$REPO/.git" ] || { record SKIP gitignore "not a git repo"; return; }
  # Derived from the repo's own .gitignore, never a fixed list: a hardcoded set
  # has to be edited every time a repo gains a secret, and silently reports a
  # clean bill for everything it was never told about.
  #
  # Backup variants are swept separately because they are what actually leaks —
  # an ignore rule for profile.toml does not cover profile.toml.bak, and that
  # exact gap had to be caught by hand twice.
  # Ask git rather than interpreting .gitignore. Reading the file line by line
  # meant reimplementing negation, precedence and nesting, and it got the first
  # one wrong: skipping '!' lines while keeping '/*' left the pattern '*', so an
  # allowlist repo reported every tracked file as leaked.
  #
  # --no-index is load-bearing. check-ignore consults the index by default and
  # stays SILENT about tracked files, which is precisely the case being detected;
  # without the flag this check cannot fail.
  leaked=""
  tracked_ignored=$(git -C "$REPO" ls-files 2>/dev/null \
    | git -C "$REPO" check-ignore --no-index --stdin 2>/dev/null | head -5)
  [ -n "$tracked_ignored" ] && leaked="$leaked
    tracked despite .gitignore: $(printf '%s' "$tracked_ignored" | tr '\n' ' ')"

  backups=$(git -C "$REPO" ls-files 2>/dev/null | grep -E '\.(bak|orig|save|swp)$|\.pre-|~$' | head -5)
  [ -n "$backups" ] && leaked="$leaked
    backup variants tracked: $(printf '%s' "$backups" | tr '\n' ' ')"

  # Credential-shaped filenames the repo may simply never have thought to ignore.
  unguarded=$(git -C "$REPO" ls-files 2>/dev/null \
    | grep -Ei '(^|/)(\.env|secrets?|credentials?|id_rsa|.*\.pem|.*\.key)(\.|$)' \
    | grep -vE '\.(example|sample)$' | head -5)
  [ -n "$unguarded" ] && leaked="$leaked
    credential-shaped files tracked: $(printf '%s' "$unguarded" | tr '\n' ' ')"

  rules=$(grep -cvE '^\s*(#|!|$)' "$REPO/.gitignore" 2>/dev/null || echo 0)
  if [ -z "$leaked" ]; then
    record PASS gitignore "$rules ignore rule(s) hold; no backup or credential-shaped files tracked"
  else
    n=$(printf '%s\n' "$leaked" | grep -c '[^[:space:]]')
    record FAIL gitignore "$(printf '%s leak(s) found%s' "$n" "$leaked")"
  fi
}

# ---------------------------------------------------------------- 5. smoke
run_smoke() {
  case "$KIND" in
    python)
      # A module inside a package must be run with -m; invoking the file directly
      # fails on its own relative imports and reads as a broken entry point.
      entry="" ; how=""
      for pkg in "$(basename "$REPO")" src; do
        for m in cli __main__; do
          if [ -f "$REPO/$pkg/$m.py" ] && [ -f "$REPO/$pkg/__init__.py" ]; then
            entry="$pkg.$m"; how="module"; break 2
          fi
        done
      done
      if [ -z "$entry" ]; then
        for c in main.py cli.py; do [ -f "$REPO/$c" ] && { entry="$c"; how="file"; break; }; done
      fi
      [ -z "$entry" ] && { record SKIP smoke "no obvious entry point"; return; }
      if [ "$how" = "module" ]; then out=$("$PY3" -m "$entry" --help 2>&1); rc=$?
      else out=$("$PY3" "$entry" --help 2>&1); rc=$?; fi
      # argparse exits 0 on --help; anything else means the entry point is broken.
      if [ "$rc" -eq 0 ]; then record PASS smoke "$entry --help runs"
      else record FAIL smoke "$entry --help exited $rc: $(printf '%s' "$out" | tail -5)"; fi ;;
    node)  record SKIP smoke "define a smoke script to enable" ;;
    ruby)  record SKIP smoke "define a smoke script to enable" ;;
    swift) record SKIP smoke "define a smoke script to enable" ;;
    *)     record SKIP smoke "unknown project type" ;;
  esac
}

# ------------------------------------------------- 6. the dependency promise
run_promise() {
  readme=""
  for c in README.md readme.md README; do [ -f "$REPO/$c" ] && { readme="$REPO/$c"; break; }; done
  [ -z "$readme" ] && { record SKIP promise "no README to hold to"; return; }
  if ! grep -qiE 'stdlib only|no dependencies|no third.party|zero dependencies|no install step' "$readme"; then
    record SKIP promise "README makes no dependency promise"
    return
  fi
  [ "$KIND" = "python" ] || { record SKIP promise "promise check only implemented for python"; return; }
  out=$("$PY3" - "$REPO" <<'PY'
import ast, pathlib, sys
root = pathlib.Path(sys.argv[1])
stdlib = sys.stdlib_module_names
# A dependency promise is about RUNTIME. Development tooling — a linter, a test
# runner, an eval harness — is a separate contract, and flagging it would make the
# tool built to catch false confidence produce a false positive of its own.
DEV = {"tests", "test", "eval", "evals", "benchmarks", "bench", "tools", "scripts",
       ".github", "docs", "examples", "__pycache__", ".git"}
def is_runtime(path):
    parts = set(path.parts)
    return not (parts & DEV) and not path.name.startswith("test_")
local = {p.stem for p in root.rglob("*.py") if ".git" not in p.parts}
local |= {d.name for d in root.iterdir() if d.is_dir()}
bad = []
for path in root.rglob("*.py"):
    if not is_runtime(path.relative_to(root)):
        continue
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module] if node.module and node.level == 0 else []
        else:
            continue
        for n in names:
            r = n.split(".")[0]
            if r not in stdlib and r not in local:
                bad.append(f"{path.relative_to(root)}: {n}")
for b in sorted(set(bad)):
    print(b)
PY
)
  if [ -z "$out" ]; then record PASS promise "README promises stdlib only; the runtime holds to it"
  else record FAIL promise "README promises stdlib only, but: $out"; fi
}

# --only runs a single check. It exists because the checks have to be testable
# in isolation: running the whole gate against this repo re-enters run_tests,
# which runs the suite that invoked it.
if [ -n "$ONLY" ]; then
  case "$ONLY" in
    tests) run_tests ;; lint) run_lint ;; secrets) run_secrets ;;
    gitignore) run_gitignore ;; smoke) run_smoke ;; promise) run_promise ;;
    *) echo "qa-gate: unknown check: $ONLY" >&2; exit 2 ;;
  esac
else
  run_tests; run_lint; run_secrets; run_gitignore; run_smoke; run_promise
fi

echo "qa-gate — $(basename "$REPO") ($KIND)"
echo
for r in "${RESULTS[@]}"; do
  v="${r%%|*}"; rest="${r#*|}"; name="${rest%%|*}"; detail="${rest#*|}"
  printf '  %-4s  %-10s  %s\n' "$v" "$name" "$(printf '%s' "$detail" | head -1)"
  if [ "$v" = "FAIL" ]; then printf '%s\n' "$detail" | tail -n +2 | sed 's/^/                        /'; fi
done
echo
[ -n "$PY3" ] && echo "  python: $PY3 ($PY3_VER)" && echo
if [ "$FAILED" -eq 0 ]; then
  echo "PASS — ready for a human to drive. This is not permission to push."
  exit 0
fi
echo "FAIL — evidence above."
exit 1
