#!/usr/bin/env bash
# =============================================================================
# BookTalent — Nightly MongoDB backup
# =============================================================================
# Dumps the booktalent database to a timestamped .gz archive on a separate
# volume, prunes anything older than the retention window, and (optionally)
# ships the newest archive to S3-compatible object storage.
#
# Install on VPS:
#   sudo cp /app/deploy/backup_mongo.sh /usr/local/bin/booktalent-backup
#   sudo chmod +x /usr/local/bin/booktalent-backup
#   sudo cp /app/deploy/booktalent-backup.cron /etc/cron.d/booktalent-backup
#
# Verify a run manually:
#   sudo /usr/local/bin/booktalent-backup
#   ls -lh /var/backups/booktalent/
# =============================================================================

set -euo pipefail

# ─── Config (override via /etc/default/booktalent-backup if it exists) ──────
BACKUP_DIR="${BACKUP_DIR:-/var/backups/booktalent}"
MONGO_URI="${MONGO_URI:-mongodb://localhost:27017}"
DB_NAME="${DB_NAME:-booktalent}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

# Optional S3 (rclone) offsite copy — leave S3_REMOTE empty to skip.
# Example:  S3_REMOTE="s3-backup:booktalent-backups/"
S3_REMOTE="${S3_REMOTE:-}"

# Optional Slack webhook to notify on failure (only). Empty = silent.
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"

# Read the above overrides if a defaults file is present.
if [ -r /etc/default/booktalent-backup ]; then
    # shellcheck disable=SC1091
    . /etc/default/booktalent-backup
fi

# ─── Setup ───────────────────────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TIMESTAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT_FILE="$BACKUP_DIR/booktalent-$TIMESTAMP.archive.gz"
LOG_FILE="$BACKUP_DIR/booktalent-$TIMESTAMP.log"

log() {
    echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG_FILE"
}

notify_slack_failure() {
    local msg="$1"
    if [ -n "$SLACK_WEBHOOK_URL" ]; then
        curl -fsS -X POST -H 'Content-Type: application/json' \
            --data "{\"text\":\":rotating_light: BookTalent backup FAILED — $msg\"}" \
            "$SLACK_WEBHOOK_URL" >/dev/null || true
    fi
}

trap 'notify_slack_failure "see $LOG_FILE"' ERR

# ─── Dump ────────────────────────────────────────────────────────────────────
log "Starting mongodump ($DB_NAME) → $OUT_FILE"

# --archive + --gzip = single compressed file, easy to ship and mongorestore.
mongodump \
    --uri="$MONGO_URI" \
    --db="$DB_NAME" \
    --archive="$OUT_FILE" \
    --gzip \
    --quiet 2>>"$LOG_FILE"

SIZE_HUMAN=$(du -h "$OUT_FILE" | cut -f1)
log "Dump complete: $SIZE_HUMAN"

# ─── Integrity self-check ───────────────────────────────────────────────────
# `gunzip -t` verifies the gzip stream is not truncated.
gunzip -t "$OUT_FILE" 2>>"$LOG_FILE"
log "Integrity check OK"

# ─── Retention prune ────────────────────────────────────────────────────────
BEFORE_COUNT=$(find "$BACKUP_DIR" -maxdepth 1 -name '*.archive.gz' | wc -l)
find "$BACKUP_DIR" -maxdepth 1 -name '*.archive.gz' -mtime "+$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -name '*.log'        -mtime "+$RETENTION_DAYS" -delete
AFTER_COUNT=$(find "$BACKUP_DIR" -maxdepth 1 -name '*.archive.gz' | wc -l)
log "Retention: kept $AFTER_COUNT of $BEFORE_COUNT archives (>${RETENTION_DAYS}d pruned)"

# ─── Optional offsite copy ──────────────────────────────────────────────────
if [ -n "$S3_REMOTE" ]; then
    if command -v rclone >/dev/null 2>&1; then
        log "Uploading to $S3_REMOTE"
        rclone copy "$OUT_FILE" "$S3_REMOTE" --quiet 2>>"$LOG_FILE"
        log "Offsite copy complete"
    else
        log "S3_REMOTE set but rclone not installed — skipping offsite copy"
    fi
fi

log "Backup finished successfully"
exit 0
