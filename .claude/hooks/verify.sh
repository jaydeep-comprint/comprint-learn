#!/bin/bash
# Stop: run `make check` before Claude finishes; failures are sent back so Claude fixes them.
# No-op until a Makefile with a `check` target exists, or when nothing has changed.
input=$(cat)
# Prevent infinite loops: if we already blocked once this turn, let Claude stop.
[ "$(echo "$input" | jq -r '.stop_hook_active')" = "true" ] && exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0

[ -f Makefile ] && grep -q '^check:' Makefile || exit 0
# Skip if the working tree is clean (e.g. a pure Q&A turn).
[ -z "$(git status --porcelain 2>/dev/null)" ] && exit 0

if ! out=$(make check 2>&1); then
  echo "make check failed. Fix the root cause before finishing (don't skip or silence checks):" >&2
  echo "$out" | tail -n 60 >&2
  exit 2
fi
exit 0
