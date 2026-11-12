# Runbook: backups and restore

Spec 015 §2. **Recovery point: 24 h. Recovery time target: 1 h. Retention: 14 nightly copies.**

| What | Where |
|---|---|
| Nightly job | `.github/workflows/backup.yml`, 19:30 UTC (01:00 IST) + manual "Run workflow" |
| Output | an artifact `backup-<run id>` (14 days): `public-<ts>.dump.gpg`, `auth-<ts>.dump.gpg`, `SHA256SUMS` |
| By hand | `make backup` → `backups/` (gitignored); `make restore-check FILE=backups/public-<ts>.dump.gpg` |
| Scripts | `scripts/backup.sh`, `scripts/restore_check.sh` |

Each run dumps the `public` schema (`pg_dump --format=custom --no-owner --no-privileges`) and the
**data only** of `auth.users` and `auth.identities` (accounts and password hashes), pipes both
through `gpg --symmetric --cipher-algo AES256` (a plain dump never touches disk), then restores the
public dump into a scratch Postgres of the same major version and checks it: alembic revision,
row counts, at least one school, RLS on every table, and that the auth dump holds both tables.

GitHub artifacts are visible to everyone with access to the repo: **the encryption is what
protects them.** Supabase free projects have no backups of their own.

## 1. Setup (once, before real data)
1. Generate a passphrase: `openssl rand -base64 32`.
2. **Store it in the team password manager first** (entry "Learning app: backup passphrase").
   Not only in GitHub: a secret can't be read back from GitHub, and without the passphrase every
   backup is unrecoverable.
3. GitHub → repo Settings → Environments → `production` (deployments limited to `main`) → add
   secrets:
   - `BACKUP_DATABASE_URL`: the production **Session pooler** URL (port 5432), the same form as
     `DATABASE_URL`.
   - `BACKUP_PASSPHRASE`: the passphrase from step 1.
4. Actions → Backup → **Run workflow** on `main` (the `production` environment only allows
   `main`, so a run from a feature branch is rejected rather than "skipped"). Expect green with an artifact. Without the secrets the run is
   green and prints "skipped".
5. Record a restore drill (section 4) within the first week.

Locally: `pg_dump`/`psql`/`pg_restore` of at least the server's major version (macOS:
`brew install libpq && brew link --force libpq`) and `gpg` (`brew install gnupg`). The scripts
stop with an install hint if either is missing or too old.

## 2. Get a backup
- From GitHub: Actions → Backup → the run → Artifacts → download `backup-<id>.zip`, unzip.
- Verify: `shasum -a 256 -c SHA256SUMS`.
- Decrypt (only when restoring; the plain dump then exists on disk, delete it after):
  `gpg --decrypt public-<ts>.dump.gpg > public.dump` (asks for the passphrase).

## 3. Full restore into a new Supabase project
Use when the project is lost or a bad migration/import destroyed data. Expected time: 30–60 min.

1. Supabase → New project (same region, `ap-south-1`). Note its Session pooler URL.
2. Settings: Authentication → **turn off "Allow new users to sign up"**; set Site URL and the
   redirect allow-list to `APP_URL` (docs/runbooks/deploy-checklist.md).
3. Restore the public schema (no `alembic upgrade` needed: the dump has the schema and
   `alembic_version`). The dump creates `public` itself, so drop the new project's empty one first
   (a brand-new project only: check it has no tables):
   ```
   psql "<new Session pooler URL>" -c "drop schema public cascade;"
   gpg --decrypt public-<ts>.dump.gpg \
     | pg_restore --exit-on-error --no-owner --no-privileges -d "<new Session pooler URL>"
   ```
4. Load the auth data. **Not yet drilled**: restoring `auth.users` and `auth.identities` into a
   fresh project is expected to work because both tables are created by Supabase with the same
   columns, but check the project's auth schema version first:
   ```
   gpg --decrypt auth-<ts>.dump.gpg \
     | pg_restore --data-only --no-owner -d "<new URL>"
   ```
   (`--disable-triggers` needs a superuser, which Supabase's `postgres` role is not; load
   `auth.users` before `auth.identities`, the dump's order.)
   If it fails on a column mismatch, users can still be recovered: teachers re-invite (same email
   → same row), and students get new passwords from "Reset password" (their `app_user` rows and
   learning history are intact). Record what happened here.
5. Check RLS is on everywhere (the dump keeps it, but confirm):
   `select relname from pg_class c join pg_namespace n on n.oid=c.relnamespace where nspname='public' and relkind='r' and not relrowsecurity;` → no rows.
6. Point the API's `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` and the SPA's
   `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` at the new project, redeploy, and update the
   `BACKUP_DATABASE_URL` and `PROD_*` secrets.
7. Smoke test: sign in as a teacher and a student, open a lesson, answer a question.

## 4. Restore drills
Run `make restore-check` (or the workflow) monthly and before the pilot. Record each one:

| Date | Who | Source | Duration | Result |
|---|---|---|---|---|
| 2026-11-12 | Claude (spec 015 PR 2) | `make backup` of the **dev** project (Postgres 17.11, pg_dump 18.6) → `make restore-check` into a local Homebrew Postgres 17.11 | backup 5 s (224 KB + 3 KB encrypted), restore + checks 3 s | OK: `0013_privacy` = repo head, 37 tables with counts, 1 organization, RLS on every table, auth dump holds `auth.users` + `auth.identities`. Also checked: refuses a non-empty target, refuses a Supabase URL, a wrong passphrase fails. Auth-data load into a new Supabase project: not drilled |

## 5. Troubleshooting
- **"could not read the server version"**: the Supabase free project is paused (idle ~1 week).
  Restore it in the dashboard, then rerun.
- **"pg_dump N is older than the server"**: install the matching client (the workflow does this
  from PGDG automatically).
- **Dump over 500 MB**: the workflow warns; not expected at pilot scale (a school is a few MB).
- **Passphrase lost**: existing backups are unrecoverable. Generate a new one, store it, update
  the secret, run the workflow, and delete the old artifacts.
