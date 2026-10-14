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
4. If the feature isn't listed in docs/PRD.md's MVP scope, add it there with a link to the spec.
5. Reply with the spec path and a 3-line summary. Recommend implementing it in a fresh session:
   "Implement docs/specs/NNN-slug.md. Plan first."
