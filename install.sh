#!/usr/bin/env bash
# install.sh — wire this clone into ~/.local/bin and ~/.claude/skills.
# Idempotent; re-run after moving the clone.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
SKILL_LINK="$HOME/.claude/skills/fps"

mkdir -p "$BIN_DIR"

shim() { # name, target, interpreter ("" = exec directly)
  local name="$1" target="$2" interp="${3:-}"
  local path="$BIN_DIR/$name"
  if [ "$interp" = "python3" ]; then
    printf '#!/usr/bin/env bash\nexec python3 "%s" "$@"\n' "$target" > "$path"
  else
    printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "$target" > "$path"
  fi
  chmod +x "$path"
  echo "  $name -> $target"
}

echo "shims in $BIN_DIR:"
shim fps          "$REPO_DIR/scripts/fps"
shim fps-services "$REPO_DIR/scripts/fps_services.py" python3
shim fps-learn    "$REPO_DIR/scripts/fps_learn.py"    python3
shim fps-loops    "$REPO_DIR/scripts/fps_state.py"    python3
shim fps-bootstrap "$REPO_DIR/scripts/fps_bootstrap.py" python3
shim fps-tenant  "$REPO_DIR/scripts/fps_tenant.py"    python3

mkdir -p "$(dirname "$SKILL_LINK")"
if [ -L "$SKILL_LINK" ] || [ ! -e "$SKILL_LINK" ]; then
  ln -sfn "$REPO_DIR" "$SKILL_LINK"
  echo "skill: $SKILL_LINK -> $REPO_DIR"
else
  echo "skill: $SKILL_LINK exists and is not a symlink — left untouched" >&2
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "note: $BIN_DIR is not on your PATH" >&2 ;;
esac
