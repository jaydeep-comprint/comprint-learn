#!/bin/bash
# PostToolUse (Edit|Write): format the edited file with whatever formatter the project has.
# Silent no-op until a formatter is installed.
file=$(jq -r '.tool_input.file_path // empty')
[ -z "$file" ] || [ ! -f "$file" ] && exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0

case "$file" in
  *.js|*.jsx|*.ts|*.tsx|*.json|*.css|*.scss|*.html|*.md|*.yml|*.yaml)
    [ -x node_modules/.bin/prettier ] && node_modules/.bin/prettier --write --log-level silent "$file" ;;
  *.py)
    command -v ruff >/dev/null && { ruff format -q "$file"; ruff check -q --fix "$file"; } ;;
  *.go)
    command -v gofmt >/dev/null && gofmt -w "$file" ;;
  *.rs)
    command -v rustfmt >/dev/null && rustfmt -q "$file" ;;
esac
exit 0
