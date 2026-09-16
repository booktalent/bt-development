#!/usr/bin/env bash
# BookTalent — daily MongoDB backup
# Called by cron at 03:15 IST.  Keeps last 14 days of dumps.
# --------------------------------------------------------------------
set -euo pipefail

BACKUP_DIR="/var/backups/booktalent/mongo"
RETENTION_DAYS=14
TS=$(date -u +%Y%m%d-%H%M%S)
DUMP_PATH="$BACKUP_DIR/dump-$TS"

mkdir -p "$BACKUP_DIR"

echo "[$(date -u -Iseconds)] Starting mongodump → $DUMP_PATH"
mongodump \
    --uri="mongodb://localhost:27017" \
    --db=booktalent \
    --out="$DUMP_PATH" \
    --gzip

# Tarball + drop the raw dir
tar -C "$BACKUP_DIR" -czf "$DUMP_PATH.tar.gz" "dump-$TS"
rm -rf "$DUMP_PATH"

echo "[$(date -u -Iseconds)] Backup written: $DUMP_PATH.tar.gz ($(du -h $DUMP_PATH.tar.gz | cut -f1))"

# Prune old backups
find "$BACKUP_DIR" -name "dump-*.tar.gz" -mtime +"$RETENTION_DAYS" -delete
echo "[$(date -u -Iseconds)] Pruned dumps older than $RETENTION_DAYS days"

# OPTIONAL: sync to S3 / off-site storage — uncomment and configure aws-cli
# aws s3 cp "$DUMP_PATH.tar.gz" "s3://booktalent-backups/mongo/" --storage-class STANDARD_IA
