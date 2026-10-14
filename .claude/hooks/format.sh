#!/bin/bash
# PostToolUse (Edit|Write): format the edited file with the app's own formatter.
# frontend/** -> prettier from frontend/node_modules; backend/**/*.py -> ruff via uv. Other paths are left alone.
# Silent no-op if the formatter isn't installed yet (run `make install`).
file=$(jq -r '.tool_input.file_path // empty')
[ -z "$file" ] || [ ! -f "$file" ] && exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0

case "$file" in
  "$CLAUDE_PROJECT_DIR"/*) rel="${file#"$CLAUDE_PROJECT_DIR"/}" ;;
  /*) exit 0 ;;
  *) rel="$file" ;;
esac

case "$rel" in
  frontend/*.js|frontend/*.jsx|frontend/*.ts|frontend/*.tsx|frontend/*.json|frontend/*.css|frontend/*.html|frontend/*.md|frontend/*.yml|frontend/*.yaml)
    [ -x frontend/node_modules/.bin/prettier ] &&
      (cd frontend && node_modules/.bin/prettier --write --ignore-unknown --log-level silent "${rel#frontend/}") ;;
  backend/*.py)
    command -v uv >/dev/null &&
      uv run --directory backend ruff format -q "${rel#backend/}" &&
      uv run --directory backend ruff check -q --fix "${rel#backend/}" ;;
esac
exit 0
