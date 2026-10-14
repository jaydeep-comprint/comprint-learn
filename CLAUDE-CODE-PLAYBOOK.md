# Claude Code Playbook: Building a Product with Claude

> Gathered October 2026 from Anthropic's official docs, the Claude Code creator's published workflow, and the main community lists and plugin rankings.
> Reddit could not be read directly (fetching was blocked and its threads didn't show up in search results), so the "community" picks here come from blogs, newsletters and GitHub lists that summarize r/ClaudeAI and r/ClaudeCode.
> **Before installing anything, check the install commands with `/plugin` in a live session.** The catalog changes often.

---

## 0. TL;DR: the 10 rules that matter most

1. **Give Claude a way to check its work** (tests, build, lint, screenshots). This is Anthropic's #1 tip. Boris Cherny, who created Claude Code, says it improves results 2–3×.
2. **Write the spec before the code.** Have Claude interview you, save the result to `SPEC.md`, then build it in a *fresh* session.
3. **Start in plan mode** (Shift+Tab). Cherny begins about 80% of his sessions there.
4. **Keep CLAUDE.md short (under about 200 lines)** and hand-edited. Every time Claude makes a mistake, add a line.
5. **Skills are for knowledge that's only sometimes needed. Hooks are for anything that must always happen.**
6. **Context is your scarcest resource.** Run `/clear` between tasks. After two failed corrections, `/clear` and write a better prompt.
7. **Use subagents** for research, so file dumps stay out of your main context, and for reviews, so a fresh pair of eyes checks the work.
8. **Install only a few plugins.** Each one costs context, so turn off the ones you aren't using.
9. **Use CLI tools (`gh`, etc.) before MCP when possible.** They use the least context.
10. **Commit often.** Use git worktrees to run several Claude sessions in parallel.

---

## 1. Project structure

```
my-product/
├── CLAUDE.md                 # always loaded; short; committed
├── CLAUDE.local.md           # personal notes; gitignored
├── .mcp.json                 # project MCP servers (committed)
├── docs/
│   ├── PRD.md                # product brief: problem, users, MVP scope, non-goals
│   ├── ARCHITECTURE.md       # stack + key decisions (linked from CLAUDE.md via @)
│   └── specs/
│       └── 001-auth.md       # one spec per feature
└── .claude/
    ├── settings.json         # permissions + hooks (committed)
    ├── settings.local.json   # personal overrides (gitignored)
    ├── skills/<name>/SKILL.md   # on-demand knowledge + /slash-commands
    └── agents/<name>.md         # custom subagents (reviewer, tester...)
```

**Where config lives and who it applies to**
| Location | Scope |
|---|---|
| `~/.claude/CLAUDE.md`, `~/.claude/skills/` | You, in every project |
| `./CLAUDE.md`, `./.claude/` | The whole team (commit to git) |
| `./CLAUDE.local.md`, `.claude/settings.local.json` | You, in this project only (gitignore) |

---

## 2. PRD and spec workflow (spec-driven development)

**The documents, written in this order and each reviewed by you:**
1. **PRD.md**: written once for the product. It covers who the product is for, the problem, success metrics, the MVP feature list and **non-goals**.
2. **specs/NNN-feature.md**: one per feature. It covers what the feature does, which files and interfaces it touches, what's out of scope, edge cases, and an **end-to-end verification step**.
3. **Plan**: created in plan mode as numbered tasks (file, change, order, test). Press Ctrl+G to edit it.
4. **Code**: built against the plan, with tests run after each task.

**Interview prompt (from Anthropic's docs):**
```
I want to build [brief description]. Interview me in detail using the AskUserQuestion tool.
Ask about technical implementation, UI/UX, edge cases, concerns, and tradeoffs.
Don't ask obvious questions, dig into the hard parts I might not have considered.
Keep interviewing until we've covered everything, then write a complete spec to docs/specs/NNN-name.md.
```
Then **start a fresh session** to build it: "Implement docs/specs/001-auth.md. Plan first."

**Skip the plan** for tiny changes. If you can describe the diff in one sentence, just ask for it.

**Optional frameworks** that enforce this process: Superpowers (the most popular), GitHub Spec Kit, BMAD-METHOD, Agent OS, and planning-with-files.

---

## 3. CLAUDE.md

Run `/init` to generate a starter, then **prune it ruthlessly**. Check every line by asking: *"Would removing this cause Claude to make mistakes?"*

| ✅ Include | ❌ Exclude |
|---|---|
| Build, test and lint commands Claude can't guess | Anything Claude can learn by reading the code |
| Style rules that differ from the defaults | Standard language conventions |
| Preferred test runner and how to run a single test | Long API docs (link to them instead) |
| Branch and PR conventions | Information that changes often |
| Architecture decisions specific to this project | Tutorials or long explanations |
| Environment quirks (required env vars) | File-by-file descriptions of the codebase |
| A "common mistakes" list (grows over time) | "Write clean code" and other generic advice |

**Template**
```markdown
# Project: <name>
<one-line what it is>. Full context: @docs/PRD.md, @docs/ARCHITECTURE.md

## Commands
- Dev: `pnpm dev` | Test one: `pnpm test path/to/file` | Typecheck: `pnpm typecheck` | Lint: `pnpm lint`

## Rules
- After any code change: typecheck + run related tests. Show the output.
- New features start from a spec in docs/specs/.
- <stack-specific rules that differ from defaults>

## Gotchas
- <add one line every time Claude gets something wrong>

## Compaction
- When compacting, preserve modified file list, current spec, and test commands.
```

**Tips**
- Use `IMPORTANT` on *one* line only. If you emphasize everything, nothing stands out.
- If Claude ignores a rule, the file is probably too long. If the rule really must be followed every time, turn it into a **hook**.
- Run `/context` to check the file loaded and `/doctor` to get suggested cuts.
- The Claude Code team keeps one shared CLAUDE.md in git and adds to it whenever Claude makes a mistake, including during PR review.

---

## 4. Skills

A skill is a folder with a `SKILL.md` in it. Claude loads it **only when it's relevant**, or you can call it with `/name`.

```markdown
# .claude/skills/api-conventions/SKILL.md
---
name: api-conventions
description: REST API conventions for our services. Use when creating or editing API endpoints.
---
- kebab-case URL paths, camelCase JSON
- Always paginate list endpoints
- Version in URL (/v1/)
```

```markdown
# .claude/skills/ship/SKILL.md   → /ship
---
name: ship
description: Run checks, commit, and open a PR
disable-model-invocation: true      # only runs when YOU call it
---
1. Run typecheck, lint, tests. Stop if anything fails.
2. Review the diff against the current spec.
3. Commit with a descriptive message, push, open PR with `gh pr create`.
```

**Best practices**
- The `description` decides when the skill triggers, so be specific. Broad descriptions make it trigger too often.
- Keep SKILL.md under about 500 lines and put long reference material in extra files in the same folder.
- Add `disable-model-invocation: true` to anything with side effects (deploy, release, migrations).
- Use `allowed-tools` to limit what a skill can do.
- Create a skill when you notice yourself repeating an instruction. Don't write them in advance.
- Use the **skill-creator** skill to scaffold and test new ones.

**Skills worth starting with for a product team**
| Skill | Purpose |
|---|---|
| `/spec` | Runs the interview and writes `docs/specs/NNN-*.md` |
| `/ship` | Runs checks, then commits and opens a PR |
| `api-conventions` / `ui-conventions` | House style, loaded only when relevant |
| `db-migrations` | How to write and run migrations safely |
| `release` | Changelog, version bump and tag (manual only) |

**Official Anthropic skills** (`anthropics/skills`, install with `/plugin marketplace add anthropics/skills`): docx, pdf, pptx, xlsx, **skill-creator**, **webapp-testing** (Playwright), frontend-design, mcp-builder, and others.

---

## 5. Plugins (bundles of skills, agents, hooks and MCP servers)

Run `/plugin` to browse. The official marketplace `claude-plugins-official` is available automatically.
Install with `/plugin install <name>@claude-plugins-official`.

### Most recommended
| Plugin | What it does | Source |
|---|---|---|
| **Superpowers** | Enforces a brainstorm → spec → plan → worktree → TDD workflow. The most-starred community plugin. | `/plugin marketplace add obra/superpowers-marketplace` → `/plugin install superpowers@superpowers-marketplace` |
| **Context7** | Up-to-date, version-specific library docs, so Claude doesn't use outdated APIs | `upstash/context7` (plugin or MCP) |
| **frontend-design** | Polished, production-grade UI instead of generic-looking output | official |
| **code-review** | Parallel agents review the diff for bugs | official |
| **security-guidance** | Flags injection, XSS and exposed secrets | official |
| **typescript-lsp** (or your language's LSP) | Go-to-definition and type errors after each edit | official |
| **GitHub** | Access to issues, PRs and repos | official (or just use the `gh` CLI) |
| **feature-dev** | A guided 7-phase feature workflow | official |
| **skill-creator** | Build and test your own skills | official |
| **claude-code-setup** | Scans your repo and recommends hooks, skills and MCP servers. Run it once per repo. | official |

### Situational
| Plugin | When to use it |
|---|---|
| planning-with-files | Keeps plans in markdown so work survives context resets |
| Playwright | End-to-end tests and UI checks in a real browser |
| pr-review-toolkit, code-simplifier, commit-commands | Cleanup, PR reviews and commits |
| Claude Mem | Memory across sessions |
| ui-ux-pro-max | Heavier UI/UX guidance |
| Ralph Wiggum | Long autonomous loops (popular, but use carefully) |
| ECC | A large, opinionated harness for power users |

> Rule: **install only a few, and turn off what you're not using.** Each plugin adds to the system prompt.

---

## 6. MCP servers

Add one with `claude mcp add <name> -- <command>`, or commit them to `.mcp.json` for the team.

| Server | Use it for |
|---|---|
| **Context7** | Fresh framework docs: `claude mcp add context7 -- npx -y @upstash/context7-mcp` |
| **Playwright** | Browser automation and UI checks: `claude mcp add playwright -- npx @playwright/mcp@latest` (uses a lot of tokens on big pages) |
| **GitHub** | Issues and PRs (the `gh` CLI is often cheaper) |
| **Supabase / Postgres** | Querying and managing your database |
| **Sentry** | Debugging production errors |
| **Figma / Notion / Linear** | Designs, docs and tickets |

Add servers as you need them, not by default. Note that many of Anthropic's original reference MCP servers were archived in 2025, so older tutorials may point to unmaintained code.

---

## 7. Hooks (always run, no exceptions)

CLAUDE.md is **advice**. Hooks are **guaranteed**. Configure them in `.claude/settings.json` and browse them with `/hooks`.
The easy way: *"Write a hook that runs prettier + eslint after every file edit."*

| Hook | Example |
|---|---|
| `PostToolUse` (Edit/Write) | Auto-format and lint the changed file |
| `PreToolUse` | Block edits to `migrations/`, `.env`, lockfiles |
| `Stop` | Run the typecheck and tests. Claude can't finish while they fail. |
| `SessionStart` | Install dependencies and load environment context |
| `Notification` | Desktop ping when Claude needs you |

---

## 8. Subagents

Put them in `.claude/agents/<name>.md`. Each runs in its **own context** with its own tools.

```markdown
---
name: reviewer
description: Reviews a diff against the spec. Use after implementing a feature.
tools: Read, Grep, Glob, Bash
---
Review the current diff against the spec named by the user. Report only gaps that
affect correctness or stated requirements; cite file:line. Ignore style preferences.
```

Useful ones: **reviewer** (diff vs. spec), **security-reviewer**, **test-writer**, **researcher** (explores the codebase or docs and returns a summary).
Prompts: *"Use subagents to investigate X"* and *"Use a subagent to review this diff against docs/specs/003.md."*
⚠️ A reviewer asked to find gaps will always find some. Tell it to report only gaps that affect correctness or the requirements.

---

## 9. Daily workflow

```
1. /clear                          (fresh context per feature)
2. Shift+Tab → plan mode
3. "Read docs/specs/004-x.md and relevant code. Make a plan."   → edit with Ctrl+G
4. Approve → Claude implements, runs tests after each step
5. "Use a subagent to review the diff against the spec"  or  /code-review
6. /ship  (or: commit + PR)
7. Anything Claude got wrong → add one line to CLAUDE.md
```

**Context management**
- `/clear` between unrelated tasks. `/compact focus on X` keeps only what you specify.
- `Esc` interrupts Claude. `Esc Esc` or `/rewind` restores code or conversation to a checkpoint.
- Use `/btw` for side questions that shouldn't stay in context.
- Name sessions with `/rename` and resume them with `claude --continue` or `--resume`.

**Scaling up**
- Use **git worktrees** to run 3–5 Claude sessions in parallel on separate features (Cherny's setup).
- Writer/reviewer pattern: session A writes the code and session B reviews it with a fresh context.
- `claude -p "..."` runs non-interactively for CI and scripts. `/batch` fans a large migration out across subagents.
- Set up permissions with `/permissions` (allowlist safe commands) and `/sandbox`, or use auto mode.

**Writing good prompts**
- ❌ "fix the login bug" → ✅ "login fails after session timeout; check src/auth token refresh; write a failing test first, then fix"
- Point to examples: "follow the pattern in `HotDogWidget.php`".
- Paste screenshots for UI work and ask Claude to compare its result with them.
- Ask Claude for **evidence** (test output, screenshots), not just a claim that it's done.

---

## 10. Common mistakes

| Mistake | Fix |
|---|---|
| Doing several unrelated tasks in one session | `/clear` between tasks |
| Correcting Claude over and over | After 2 tries, `/clear` and write a better prompt |
| A 1,000-line CLAUDE.md | Prune it. Move rules into skills or hooks. |
| Trusting code that only looks right | Always have Claude run tests, a build or a screenshot |
| Unscoped "investigate" requests | Narrow the scope or use a subagent |
| Installing 20 plugins | Start with 3–5 and turn off the rest |

---

## 11. Setup checklist for a new product

- [ ] `git init` and the first commit
- [ ] Write `docs/PRD.md` (1 page: users, problem, MVP, non-goals)
- [ ] Pick the stack and record it in `docs/ARCHITECTURE.md`
- [ ] Scaffold the project and make test, lint and typecheck commands work
- [ ] `/init` → prune CLAUDE.md using the template above
- [ ] `.claude/settings.json`: permissions allowlist, a format-on-edit hook and a Stop hook that runs tests
- [ ] Plugins: superpowers *or* feature-dev, context7, frontend-design (for UI), code-review, the LSP for your language
- [ ] Agents: `reviewer.md`
- [ ] Skills: `/spec`, `/ship`
- [ ] First feature: interview → spec → fresh session → plan → build → review → ship

---

## Sources
**Official**
- Anthropic: Best practices for Claude Code: https://code.claude.com/docs/en/best-practices
- Anthropic: Skills docs: https://code.claude.com/docs/en/skills
- Anthropic: Plugins announcement: https://anthropic.com/news/claude-code-plugins
- Anthropic: Plugin marketplaces: https://code.claude.com/docs/zh-CN/plugins/anthropic-marketplaces
- anthropics/skills: https://skills.sh/anthropics/skills

**Creator workflow (Boris Cherny)**
- InfoQ: https://infoq.com/news/2026/01/claude-code-creator-workflow/
- https://karozieminski.substack.com/p/boris-cherny-claude-code-workflow
- https://www.mejba.me/blog/boris-cherny-claude-code-workflow
- https://dev.to/sivarampg/how-the-creator-of-claude-code-uses-claude-code-a-complete-breakdown-4f07

**Plugin and skill rankings and lists**
- https://designrevision.com/blog/best-claude-code-plugins
- https://composio.dev/content/top-claude-code-plugins
- https://designrevision.com/blog/official-claude-code-plugins
- https://designrevision.com/blog/awesome-claude-code-skills.md
- hesreallyhim/awesome-claude-code (the most-starred list): https://gittrend.io/repo/hesreallyhim/awesome-claude-code
- travisvn/awesome-claude-skills: https://gittrend.io/repo/travisvn/awesome-claude-skills
- https://github.com/GetBindu/awesome-claude-code-and-skills
- https://mayalekhi.substack.com/p/my-current-claude-code-setup
- https://www.morphllm.com/claude-code-marketplace

**CLAUDE.md, spec-driven development and MCP**
- https://www.heyuan110.com/posts/ai/2026-03-05-claude-code-claudemd-best-practices/
- https://morphllm.com/claude-md-examples
- https://www.builder.io/blog/setting-up-claude-code-project
- https://datacamp.com/tutorial/spec-driven-development-with-claude-code
- https://buildermethods.com/library/spec-driven-development-claude-code
- https://augmentcode.com/guides/claude-code-spec-driven-development
- https://www.heyuan110.com/posts/ai/2026-03-05-best-mcp-servers-claude-code/
- https://composio.dev/blog/best-mcp-servers-claude-code-codex
- https://dev.to/oikon/24-claude-code-tips-claudecodeadventcalendar-52b5
- https://aicodingdaily.substack.com/p/claude-code-tips-and-wild-2026-predictions
