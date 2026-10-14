---
name: ship
description: Verify, review, commit, and open a PR for the current work.
disable-model-invocation: true
argument-hint: [spec path, e.g. docs/specs/003-auth.md]
---
Ship the current changes. Spec: $ARGUMENTS (if empty, infer it from the branch name or recent work, and say which you used).

1. Run the full check (`make check` if it exists, otherwise the typecheck/lint/test commands in CLAUDE.md).
   If anything fails, fix it or stop and report. Never skip or silence checks.
2. Use the `reviewer` subagent to review the diff against the spec. Fix findings that affect correctness
   or stated requirements; list the rest as optional.
3. If not on a feature branch, create one: `feat/<spec-number>-<slug>`.
4. Commit with a descriptive message (what + why).
5. If a GitHub remote exists and `gh` is available, push and open a PR with `gh pr create`; the body
   links the spec and includes the verification evidence. Otherwise, say what's left to do.
6. Report: branch, commit hash, PR link (if any), and check results.
