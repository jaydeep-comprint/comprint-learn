# Repo-level commands. `make check` is the offline quality gate (the Claude Stop hook and CI run it).
SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend

.PHONY: install dev dev-api dev-web check check-api check-web content-check content-import review-pack test-db migrate fmt fmt-api fmt-web audit audit-py audit-js audit-secrets backup restore-check loadtest

install:
	cd $(BACKEND) && uv sync --frozen
	cd $(FRONTEND) && pnpm install --frozen-lockfile

# API on :8000 and web on :5173 together; Ctrl-C stops both.
dev:
	$(MAKE) -j2 dev-api dev-web

# uvicorn, not `fastapi dev`: its banner queries the terminal colour over /dev/tty, and under
# `make -j2` Vite's keyboard reader can take the reply, leaving the API hung before it binds.
dev-api:
	cd $(BACKEND) && uv run uvicorn app.main:app --reload --port 8000

dev-web:
	cd $(FRONTEND) && pnpm dev

check: check-api check-web content-check

# --frozen: never re-lock or touch the network from the gate.
check-api:
	@test -d $(BACKEND)/.venv || { echo "Run 'make install' first."; exit 1; }
	cd $(BACKEND) && uv run --frozen ruff check .
	cd $(BACKEND) && uv run --frozen ruff format --check .
	cd $(BACKEND) && uv run --frozen mypy
	cd $(BACKEND) && uv run --frozen pytest -q -m "not db"

check-web:
	@test -d $(FRONTEND)/node_modules || { echo "Run 'make install' first."; exit 1; }
	cd $(FRONTEND) && pnpm exec eslint .
	cd $(FRONTEND) && pnpm exec prettier --check .
	cd $(FRONTEND) && pnpm exec tsc -b --noEmit
	cd $(FRONTEND) && pnpm exec vitest run

# Validates content/ offline (schema, graph, answers, code solutions); part of `check`.
# Strict (spec 013): warnings fail too. The CLI flag itself stays opt-in.
content-check:
	cd $(BACKEND) && uv run --frozen app content check --root ../content --strict

# One HTML file per course with every answer, for reviewers (spec 013); gitignored review-packs/.
review-pack:
	cd $(BACKEND) && uv run --frozen app content review-pack --root ../content $(ARGS)

# Imports content/ into DATABASE_URL (idempotent; add ARGS=--dry-run to preview).
content-import:
	cd $(BACKEND) && uv run app content import --root ../content $(ARGS)

# Real-database tests against TEST_DATABASE_URL (a separate Supabase project). Fails if it is unset.
test-db:
	cd $(BACKEND) && REQUIRE_DB=1 uv run --frozen pytest -q -m db

migrate:
	cd $(BACKEND) && uv run alembic upgrade head

# Spec 015: dependency and secret scanning (needs network; CI's `security` job runs the same).
# An ignore needs a line in docs/security-review.md ("## Audit ignores": id, reason, revisit date).
audit: audit-py audit-js audit-secrets

# pipefail: a failed `uv export` must not let pip-audit pass on empty input.
audit-py:
	set -o pipefail; cd $(BACKEND) && uv export --frozen --no-dev --no-emit-project --no-hashes --format requirements-txt \
		| uvx pip-audit@2.10.1 --requirement /dev/stdin --no-deps --disable-pip --format json \
		| python3 ../scripts/pip_audit_filter.py

audit-js:
	cd $(FRONTEND) && pnpm audit --prod --audit-level high

# Full history locally; CI scans the PR range on pull requests.
audit-secrets:
	@command -v gitleaks >/dev/null || { echo "gitleaks not found: brew install gitleaks (CI pins its version)"; exit 1; }
	gitleaks detect --source . --config .gitleaks.toml --redact --no-banner

# Spec 015: one school lab (80 students + 2 teachers, 10 min) against a local API on the TEST
# database; seeds it, checks the pass criteria, writes backend/loadtest/out/report.md.
# Never at the same time as `make test-db` (a lock refuses). Smoke run: ARGS="--users 30 --run-time 2m".
loadtest:
	cd $(BACKEND) && uv run --frozen --group loadtest python -m loadtest.run $(ARGS)

# Spec 015: encrypted dump of BACKUP_DATABASE_URL into backups/ (needs BACKUP_PASSPHRASE).
backup:
	./scripts/backup.sh

# Restore FILE into an empty scratch Postgres (RESTORE_DATABASE_URL) and check it.
restore-check:
	./scripts/restore_check.sh "$(FILE)"

fmt: fmt-api fmt-web

fmt-api:
	cd $(BACKEND) && uv run ruff format . && uv run ruff check --fix .

fmt-web:
	cd $(FRONTEND) && pnpm exec prettier --write .
