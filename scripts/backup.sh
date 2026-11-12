#!/usr/bin/env bash
# Spec 015: encrypted logical backup of the database (make backup).
#
# Needs BACKUP_DATABASE_URL (Supabase Session pooler URL, port 5432) and BACKUP_PASSPHRASE.
# Writes to backups/ (gitignored, or $BACKUP_DIR):
#   public-<UTC ts>.dump.gpg  pg_dump --format=custom of schema public (no owners or privileges)
#   auth-<UTC ts>.dump.gpg    data only of auth.users and auth.identities (accounts + password hashes)
#   SHA256SUMS
# Dumps are piped straight into gpg (AES256, symmetric): a plain dump never touches disk, and the
# passphrase goes through a file descriptor, never argv.
set -euo pipefail

die() { echo "backup: $*" >&2; exit 1; }

: "${BACKUP_DATABASE_URL:?BACKUP_DATABASE_URL is not set (Session pooler URL)}"
: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE is not set}"

command -v pg_dump >/dev/null || die "pg_dump not found. macOS: brew install libpq && brew link --force libpq; Ubuntu: apt install postgresql-client-<major> (PGDG)"
command -v psql >/dev/null || die "psql not found (install it with pg_dump, see above)"
command -v gpg >/dev/null || die "gpg not found. macOS: brew install gnupg; Ubuntu: apt install gnupg"

# pg_dump must be at least the server's major version.
server_major=$(psql "$BACKUP_DATABASE_URL" -XAtc "SHOW server_version" | cut -d. -f1)
client_major=$(pg_dump --version | sed -E 's/[^0-9]*([0-9]+).*/\1/')
[[ -n "$server_major" ]] || die "could not read the server version (is the project paused? see docs/runbooks/backup-restore.md)"
if (( client_major < server_major )); then
  die "pg_dump $client_major is older than the server ($server_major): install postgresql-client-$server_major"
fi

out=${BACKUP_DIR:-backups}
mkdir -p "$out"
chmod 700 "$out"
ts=$(date -u +%Y%m%dT%H%M%SZ)
public="public-$ts.dump.gpg"
auth="auth-$ts.dump.gpg"

encrypt() {
  # fd 3 carries the passphrase; --pinentry-mode loopback lets gpg read it without a terminal.
  gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 3 \
    --symmetric --cipher-algo AES256 --output "$1" 3<<<"$BACKUP_PASSPHRASE"
}

echo "backup: public schema -> $out/$public"
pg_dump "$BACKUP_DATABASE_URL" --format=custom --no-owner --no-privileges --schema=public \
  | encrypt "$out/$public"

echo "backup: auth.users + auth.identities (data only) -> $out/$auth"
pg_dump "$BACKUP_DATABASE_URL" --format=custom --data-only --no-owner --no-privileges \
  --table=auth.users --table=auth.identities \
  | encrypt "$out/$auth"

(cd "$out" && shasum -a 256 "$public" "$auth" > SHA256SUMS 2>/dev/null \
  || sha256sum "$public" "$auth" > SHA256SUMS)

for f in "$public" "$auth"; do
  size=$(wc -c < "$out/$f" | tr -d ' ')
  echo "backup: $f $size bytes"
  if (( size > 500 * 1024 * 1024 )); then
    echo "::warning::$f is over 500 MB; GitHub artifacts may not hold it" >&2
  fi
done
echo "backup: done ($out/SHA256SUMS)"
