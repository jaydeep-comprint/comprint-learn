# <PRODUCT NAME>

Built with Claude Code. See `CLAUDE-CODE-PLAYBOOK.md` for the full workflow and research.

## Layout
| Path | Purpose |
|---|---|
| `CLAUDE.md` | Always-loaded project context (keep < 200 lines) |
| `docs/PRD.md` | Product brief: problem, users, MVP, non-goals |
| `docs/ARCHITECTURE.md` | Stack + key decisions |
| `docs/specs/` | One spec per feature (`000-TEMPLATE.md`) |
| `docs/plans/` | Plan-mode plans are saved here |
| `.claude/skills/spec` | `/spec <idea>`: interview → write a spec |
| `.claude/skills/ship` | `/ship <spec>`: check → review → commit → PR |
| `.claude/agents/` | `reviewer`, `security-reviewer` subagents |
| `.claude/hooks/` | Protect secrets/lockfiles · auto-format · run `make check` before Claude stops |
| `.mcp.json` | Context7 (up-to-date library docs) |
| `Makefile` | `make check` = the one verification command |

## Workflow
1. `/spec <feature idea>` → `docs/specs/NNN-*.md`
2. `/clear`, Shift+Tab (plan mode) → "Implement docs/specs/NNN-*.md. Plan first."
3. Approve plan → Claude builds, `make check` gates completion
4. `/ship docs/specs/NNN-*.md`
5. Claude made a mistake? Add one line to `CLAUDE.md` → Gotchas.

## One-time setup per machine
- Trust the folder when Claude Code asks (needed for allow rules & plugins).
- Plugins enabled in `.claude/settings.json`: code-review, security-guidance, frontend-design, feature-dev.
  Run `/plugin` to confirm they're installed.
- Optional: `/plugin marketplace add obra/superpowers-marketplace` then `/plugin install superpowers@superpowers-marketplace`
  (alternative to feature-dev; use one, not both).
- Install your language's LSP plugin (e.g. `/plugin install typescript-lsp@claude-plugins-official`) once the stack is chosen.
- Install `gh` and run `gh auth login` for PRs.
