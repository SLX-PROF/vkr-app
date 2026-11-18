#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
mkdir -p backups
target="backups/vkr-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose -f compose.prod.yml exec -T db sh -c 'exec pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" --format=custom' > "$target.tmp"
test -s "$target.tmp"
docker compose -f compose.prod.yml exec -T db pg_restore --list < "$target.tmp" > /dev/null
mv "$target.tmp" "$target"
printf 'Backup created: %s\n' "$target"
