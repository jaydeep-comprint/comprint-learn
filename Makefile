# `make check` is the single "is it working?" command. The Stop hook runs it before Claude finishes.
# Replace the echo with your stack's typecheck + lint + test commands once chosen, e.g.:
#   check: ; pnpm typecheck && pnpm lint && pnpm test
#   check: ; ruff check . && mypy . && pytest -q
.PHONY: check
check:
	@echo "make check: no checks configured yet (edit Makefile once the stack is chosen)"
