#!/bin/bash
# Dump Supabase postgres database from Docker container.
# Usage: ./dump_db.sh [output_file]
# Default output: exports/lnm_db_YYYYMMDD_HHMM.sql

CONTAINER="supabase_db_demo"
OUTFILE="${1:-exports/lnm_db_$(date +%Y%m%d_%H%M).sql}"

mkdir -p "$(dirname "$OUTFILE")"

echo "Dumping from $CONTAINER → $OUTFILE ..."
PGPASSWORD=postgres docker exec "$CONTAINER" pg_dump -U postgres -d postgres > "$OUTFILE"

if [ $? -eq 0 ]; then
    SIZE=$(du -sh "$OUTFILE" | cut -f1)
    echo "Done. $OUTFILE ($SIZE)"
else
    echo "Dump failed."
    exit 1
fi
