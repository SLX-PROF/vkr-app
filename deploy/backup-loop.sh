#!/bin/sh
set -u
umask 077
while true; do
    target="/backups/vkr-auto-$(date -u +%Y%m%dT%H%M%SZ).dump"
    if pg_dump --format=custom > "$target.tmp" && test -s "$target.tmp" && pg_restore --list "$target.tmp" > /dev/null; then
        mv "$target.tmp" "$target"
        printf 'Verified daily backup: %s\n' "$target"
        sleep 86400
    else
        printf 'Backup failed; retry in one hour\n' >&2
        sleep 3600
    fi
done
