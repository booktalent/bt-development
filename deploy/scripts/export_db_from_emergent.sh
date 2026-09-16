#!/usr/bin/env bash
# BookTalent — one-shot database export from the Emergent preview pod.
# Run this INSIDE the Emergent pod (the Emergent agent will do it for you).
# Output: /tmp/booktalent-dump-YYYYMMDD.tar.gz (download to your laptop)
# --------------------------------------------------------------------
set -euo pipefail

TS=$(date -u +%Y%m%d-%H%M%S)
DUMP_DIR="/tmp/booktalent-dump"
OUT="/tmp/booktalent-dump-$TS.tar.gz"

# Read MONGO_URL + DB_NAME from backend env
source /app/backend/.env

echo "▶ Dumping MongoDB database '$DB_NAME' from $MONGO_URL"
rm -rf "$DUMP_DIR"
mongodump --uri="$MONGO_URL" --db="$DB_NAME" --out="$DUMP_DIR" --gzip

echo "▶ Compressing…"
tar -czf "$OUT" -C "$(dirname $DUMP_DIR)" "$(basename $DUMP_DIR)"

SIZE=$(du -h "$OUT" | cut -f1)
COUNT=$(find "$DUMP_DIR/$DB_NAME" -name "*.bson.gz" | wc -l)

echo ""
echo "✓ Export complete."
echo "  File:        $OUT"
echo "  Size:        $SIZE"
echo "  Collections: $COUNT"
echo ""
echo "▶ Next: download this file to your laptop, then:"
echo "  scp $OUT deploy@YOUR_VPS_IP:/tmp/"
echo ""
echo "▶ On your VPS, restore with:"
echo "  tar -xzf /tmp/booktalent-dump-$TS.tar.gz -C /tmp"
echo "  mongorestore --uri=\"mongodb://localhost:27017\" --db=$DB_NAME --gzip /tmp/booktalent-dump/$DB_NAME"
