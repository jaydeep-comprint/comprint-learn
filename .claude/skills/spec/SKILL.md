---
name: spec
description: Interview the user and write a feature spec to docs/specs/. Use when the user wants to plan, scope, or spec a new feature before building it.
argument-hint: <brief feature description>
---
Write a feature spec for: $ARGUMENTS

1. Read docs/PRD.md, docs/ARCHITECTURE.md, and docs/specs/000-TEMPLATE.md. Skim relevant code if any exists.
2. Interview the user in detail with the AskUserQuestion tool. Cover behaviour, UI/UX, data, edge cases,
   failure modes, tradeoffs, and what is out of scope. Skip obvious questions; dig into the hard parts.
   Keep going until nothing important is ambiguous.
3. Pick the next free number NNN in docs/specs/ and write docs/specs/NNN-<kebab-slug>.md following the template.
   The spec must be self-contained: name files/interfaces, list out-of-scope items, and end with a concrete
   end-to-end verification section.
4. Builder check: give the spec path to a fresh subagent (general-purpose, no summary of the interview) and ask it to
   read the spec, PRD, ARCHITECTURE and relevant code as if it had to plan the implementation from them alone, and
   list every question it would need answered. Sort its questions: already answered (ignore), minor (decide, write
   the decision into the spec, mark it "(decided while specifying)"), or needs the user (ask with AskUserQuestion,
   then update the spec). Do one round only.
5. If the feature isn't listed in docs/PRD.md's MVP scope, add it there with a link to the spec.
6. Reply with the spec path, a 3-line summary and the decisions made in the builder check. Recommend implementing it in a fresh session:
   "Implement docs/specs/NNN-slug.md. Plan first."
