# DRAFT: possible playbook additions (from ray-amjad/skills)

> **Status: NOT ADOPTED. Do not apply, follow, or merge into CLAUDE-CODE-PLAYBOOK.md until we decide.**
> Drafted 2026-11-09 from a review of https://github.com/ray-amjad/skills (plugin v0.3.0, commit 0f94af3, MIT).
> Nothing has been installed. The repo's Prove It skills are labelled beta.

## Decision still open
- **Install or not:** if yes, copy only `create-prove-it`, `maintain-prove-it` and `audit-prove-it` into `~/.claude/skills/` or this repo's `.claude/skills/`. **Don't** install the whole plugin: its `task-lifecycle` and `idea-to-spec` overlap with Superpowers, and `task-lifecycle` depends on `codex exec`.
- **Where these ideas go:** §2 (spec workflow), §7/§8 (hooks and subagents), and maybe a new section on verification.

---

## Proposed: §2 PRD and spec workflow (additions)

- **Research before asking.** Never ask the user a fact the environment can answer: read the code, run the command, check the docs first.
- **Have a fresh agent critique the draft spec before the interview.** Give it the draft and the facts (with sources), not your reasoning. It looks for contradictions, unverified premises, silent decisions and missing actors. Each finding becomes a re-check or an interview question, never a silent assumption.
- **Every goal in a spec gets a surface and a check.** The surface is where a user actually meets the claim (a page, an API response, a row), and the check reads that surface. A fully mocked test doesn't prove a goal.
- **Play the spec back before writing it.** One message walks through every decision with its reason, plus a numbered list of low-stakes defaults you can veto. Auth, credentials, destructive actions and permissions always get an explicit question.

## Proposed: new section on verification (answer keys)

A check has three parts: the **surface** (where it's met), the **answer key** (what right looks like, written by someone other than the agent that built it) and the **comparison**.

**The answer-key ladder, best first:**
1. An old system that does the same job: drive both and compare
2. A snapshot of a result you know is good (a screenshot, API responses, CLI output from main)
3. An independent test suite that doesn't depend on the code it checks
4. A spec written before the code, specific enough to fail
5. Nothing: the agent decides what right means. Flag this, and move up a rung (usually by taking a snapshot from main)

**Rules:**
- **The builder fixes the app, never the answer key.** Only the user changes an answer key.
- **Check what the change touches, not the whole app.** That means new flows (checked against the spec, or parity with the thing they copy) and existing flows reached through shared code (checked against the app before the change).
- **Presence is not access.** Before relying on any env var, key or account, make one cheap logged-in call (a whoami or a list) so a blank or expired secret shows up now, not 40 minutes into a run.
- **Make checks hard to fool:**
  - Seed more than one record, some in each state.
  - Test every action in reverse too (untick, undo, delete).
  - Give stand-in providers (fake email or payments) a switch that makes them fail.
  - Assert everything the answer key names, not just the field the change is about.
  - *Why:* in the author's audit, scripted checks against a single record caught 1 of 7 planted bugs.
- **"Checks passed" isn't the verdict.** Only an agent that has looked at the evidence says PROVED, BROKEN or BLOCKED, and lists what it couldn't prove.
- **Test the verifier now and then:** plant one small realistic bug at a time (a counter off by one, a save that never happens, the right output with the wrong exit code) and see whether the check catches it. Back up the file first and revert with `cmp`, not `git checkout`.

## Proposed: §8 Subagents / §9 Daily workflow (additions)

- **One builder owns the change.** Every fix (review findings, failed checks, red CI) goes back to the agent that built it. Reviewers and verifiers are always fresh agents.
- **The verifier runs in a fresh agent** that gets only the flows, the surfaces and the answer keys, not the builder's plan or reasoning. A checker that knows what was meant sees what it expects.
- **Cap the fix loop:** at most 3 verify → fix rounds, then report what's still broken.
- **Never merge or revert on your own.** End with one question: "Merge PR #n?"
