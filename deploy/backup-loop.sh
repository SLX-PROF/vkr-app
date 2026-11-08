#!/bin/sh
set -u
umask 077
while true; do
    target="/backups/vkr-auto-$(date -u +%Y%m%dT%H%M%SZ).dump"
    media_target="$target.media.tar.gz"
    if pg_dump --format=custom > "$target.tmp" && test -s "$target.tmp" && pg_restore --list "$target.tmp" > /dev/null \
        && tar -czf "$media_target.tmp" -C /media . && tar -tzf "$media_target.tmp" > /dev/null; then
        mv "$target.tmp" "$target"
        mv "$media_target.tmp" "$media_target"
        printf 'Verified daily backup: %s\n' "$target"
        sleep 86400
    else
        printf 'Backup failed; retry in one hour\n' >&2
        sleep 3600
    fi
done
