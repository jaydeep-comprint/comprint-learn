# Repo-level commands. `make check` is the offline quality gate (the Claude Stop hook and CI run it).
BACKEND := backend
FRONTEND := frontend

.PHONY: install dev dev-api dev-web check check-api check-web test-db migrate fmt fmt-api fmt-web

install:
	cd $(BACKEND) && uv sync
	cd $(FRONTEND) && pnpm install --frozen-lockfile

# API on :8000 and web on :5173 together; Ctrl-C stops both.
dev:
	$(MAKE) -j2 dev-api dev-web

dev-api:
	cd $(BACKEND) && uv run fastapi dev app/main.py --port 8000

dev-web:
	cd $(FRONTEND) && pnpm dev

check: check-api check-web

check-api:
	cd $(BACKEND) && uv run ruff check .
	cd $(BACKEND) && uv run ruff format --check .
	cd $(BACKEND) && uv run mypy
	cd $(BACKEND) && uv run pytest -q -m "not db"

check-web:
	@test -d $(FRONTEND)/node_modules || { echo "Run 'make install' first."; exit 1; }
	cd $(FRONTEND) && pnpm exec eslint .
	cd $(FRONTEND) && pnpm exec prettier --check .
	cd $(FRONTEND) && pnpm exec tsc -b --noEmit
	cd $(FRONTEND) && pnpm exec vitest run

# Real-database tests against TEST_DATABASE_URL (a separate Supabase project). Fails if it is unset.
test-db:
	cd $(BACKEND) && REQUIRE_DB=1 uv run pytest -q -m db

migrate:
	cd $(BACKEND) && uv run alembic upgrade head

fmt: fmt-api fmt-web

fmt-api:
	cd $(BACKEND) && uv run ruff format . && uv run ruff check --fix .

fmt-web:
	cd $(FRONTEND) && pnpm exec prettier --write .
