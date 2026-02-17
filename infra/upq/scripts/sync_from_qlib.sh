#!/bin/bash
# Sync data from qlib server to upq project expected structure
# Usage: ./sync_data.sh [--dry-run]

set -e

DRY_RUN=""
if [ "$1" = "--dry-run" ]; then
    DRY_RUN="echo [DRY-RUN] "
    echo "=== DRY RUN MODE ==="
fi

SRC_DIR="/home/qlib/data"
DEST_DIR="$HOME/upq_data"

echo "Creating directory structure..."
$DRY_RUN mkdir -p "$DEST_DIR/stock/day"
$DRY_RUN mkdir -p "$DEST_DIR/stock/minute"
$DRY_RUN mkdir -p "$DEST_DIR/options/day"
$DRY_RUN mkdir -p "$DEST_DIR/options/minute"
$DRY_RUN mkdir -p "$DEST_DIR/assets"

echo "Copying stock day files..."
$DRY_RUN cp -v "$SRC_DIR"/stock/us_stocks_sip_day_aggs_v1_*.csv.gz "$DEST_DIR/stock/day/"

echo "Copying stock minute files..."
$DRY_RUN cp -v "$SRC_DIR"/stock/us_stocks_sip_minute_aggs_v1_*.csv.gz "$DEST_DIR/stock/minute/"

echo "Copying option day files (flattening year/month structure)..."
$DRY_RUN find "$SRC_DIR/us_options_opra/day_aggs_v1" -type f -name "*.csv.gz" -exec cp -v {} "$DEST_DIR/options/day/" \;

echo "Copying option minute files (flattening year/month structure)..."
$DRY_RUN find "$SRC_DIR/us_options_opra/minute_aggs_v1" -type f -name "*.csv.gz" -exec cp -v {} "$DEST_DIR/options/minute/" \;

echo "Copying treasury yields..."
$DRY_RUN cp -v "$SRC_DIR/assets/treasury_yields.csv" "$DEST_DIR/assets/"

echo ""
echo "=== Summary ==="
echo "Stock day files: $(ls -1 "$DEST_DIR/stock/day" 2>/dev/null | wc -l)"
echo "Stock minute files: $(ls -1 "$DEST_DIR/stock/minute" 2>/dev/null | wc -l)"
echo "Option day files: $(ls -1 "$DEST_DIR/options/day" 2>/dev/null | wc -l)"
echo "Option minute files: $(ls -1 "$DEST_DIR/options/minute" 2>/dev/null | wc -l)"
echo "Treasury yields: $(ls -1 "$DEST_DIR/assets/treasury_yields.csv" 2>/dev/null | wc -l)"
echo ""
echo "Done! Data synced to $DEST_DIR"
