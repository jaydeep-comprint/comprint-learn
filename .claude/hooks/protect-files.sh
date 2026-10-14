#!/bin/bash
# PreToolUse (Edit|Write): block edits to secrets and lockfiles.
file=$(jq -r '.tool_input.file_path // empty')
[ -z "$file" ] && exit 0

case "$(basename "$file")" in
  .env.example) exit 0 ;;
  .env|.env.*|package-lock.json|pnpm-lock.yaml|yarn.lock|bun.lockb|poetry.lock|uv.lock|Cargo.lock|Gemfile.lock)
    echo "Blocked: $file is protected (secrets or lockfile). Use the package manager, or ask the user to edit it." >&2
    exit 2 ;;
esac
exit 0
