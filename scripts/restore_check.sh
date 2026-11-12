#!/usr/bin/env bash
# Spec 015: prove a backup restores (make restore-check FILE=backups/public-....dump.gpg).
#
# Needs RESTORE_DATABASE_URL: an EMPTY scratch Postgres (local Docker or the workflow's
# container), never a Supabase project that holds data: it refuses if `public` has any table.
# Decrypts with BACKUP_PASSPHRASE, restores, then checks: the alembic revision is the repo head
# or an ancestor, row counts per table, at least one organization, RLS on every table. It also
# decrypts the matching auth dump and checks it holds the two TABLE DATA entries.
set -euo pipefail

die() { echo "restore-check: FAIL: $*" >&2; exit 1; }

file=${1:-${FILE:-}}
[[ -n "$file" && -f "$file" ]] || die "usage: make restore-check FILE=backups/public-<ts>.dump.gpg"
: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is not set (an empty scratch Postgres)}"
: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE is not set}"
for tool in pg_restore psql gpg; do
  command -v "$tool" >/dev/null || die "$tool not found (macOS: brew install libpq gnupg)"
done

here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")
case "$RESTORE_DATABASE_URL" in
  *supabase.co*|*supabase.com*) die "RESTORE_DATABASE_URL points at Supabase: use an empty scratch Postgres" ;;
esac

q() { psql "$RESTORE_DATABASE_URL" -XAtqv ON_ERROR_STOP=1 -c "$1"; }

existing=$(q "select count(*) from pg_tables where schemaname = 'public'")
[[ "$existing" == "0" ]] || die "the target already has $existing table(s) in public: refusing"

decrypt() {
  gpg --batch --quiet --pinentry-mode loopback --passphrase-fd 3 --decrypt "$1" 3<<<"$BACKUP_PASSPHRASE"
}

echo "restore-check: restoring $file"
q "drop schema if exists public cascade; create schema public;" >/dev/null
# Supabase roles referenced by the dump may not exist in a plain Postgres: --no-owner,
# --no-privileges (and the dump was taken with both).
decrypt "$file" | pg_restore --exit-on-error --no-owner --no-privileges -d "$RESTORE_DATABASE_URL"

# 1. Alembic revision: the repo head or one of its ancestors.
revision=$(q "select version_num from public.alembic_version")
[[ -n "$revision" ]] || die "no alembic revision in the dump"
known=$(ls "$repo/backend/alembic/versions" | sed -nE 's/^([0-9]{4}_[a-z0-9_]+)\.py$/\1/p' | sort)
head=$(echo "$known" | tail -1)
echo "$known" | grep -qx "$revision" || die "revision $revision is not in this repo (head $head)"
echo "restore-check: alembic revision $revision (repo head $head)"

# 2. Row counts per table.
echo "restore-check: row counts"
tables=$(q "select tablename from pg_tables where schemaname = 'public' order by 1")
for t in $tables; do
  printf '  %-28s %s\n' "$t" "$(q "select count(*) from public.\"$t\"")"
done

# 3. At least one school.
orgs=$(q "select count(*) from public.organization")
(( orgs >= 1 )) || die "organization is empty"

# 4. RLS on every table.
no_rls=$(q "select string_agg(c.relname, ', ') from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity")
[[ -z "$no_rls" ]] || die "RLS is off on: $no_rls"
echo "restore-check: RLS enabled on every table"

# 5. The auth dump from the same run.
auth="$(dirname "$file")/$(basename "$file" | sed 's/^public-/auth-/')"
[[ -f "$auth" ]] || die "missing $auth"
entries=$(decrypt "$auth" | pg_restore --list | grep -cE 'TABLE DATA auth (users|identities)( |$)' || true)
[[ "$entries" == "2" ]] || die "$auth should hold TABLE DATA for auth.users and auth.identities (found $entries)"
echo "restore-check: auth dump holds auth.users and auth.identities"

echo "restore-check: OK ($orgs organization(s))"
