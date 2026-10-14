# Repo-level commands. `make check` is the offline quality gate (the Claude Stop hook and CI run it).
BACKEND := backend

.PHONY: check check-api test-db migrate fmt fmt-api

check: check-api

check-api:
	cd $(BACKEND) && uv run ruff check .
	cd $(BACKEND) && uv run ruff format --check .
	cd $(BACKEND) && uv run mypy
	cd $(BACKEND) && uv run pytest -q -m "not db"

# Real-database tests against TEST_DATABASE_URL (a separate Supabase project). Fails if it is unset.
test-db:
	cd $(BACKEND) && REQUIRE_DB=1 uv run pytest -q -m db

migrate:
	cd $(BACKEND) && uv run alembic upgrade head

fmt: fmt-api

fmt-api:
	cd $(BACKEND) && uv run ruff format . && uv run ruff check --fix .
