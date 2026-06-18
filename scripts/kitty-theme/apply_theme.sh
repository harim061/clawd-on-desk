#!/usr/bin/env bash
# apply_theme.sh — Process sticker sheet and install Kitty theme
# Usage: bash apply_theme.sh <path-to-sticker-sheet.png>
set -e

SHEET="${1:-}"
if [ -z "$SHEET" ]; then
  echo "Usage: bash apply_theme.sh <sticker-sheet.png>"
  echo ""
  echo "Save the 8-pose sticker sheet image as a PNG/JPG and pass its path."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Clawd Kitty Theme Installer ==="
echo "Sheet: $SHEET"

python3 "$SCRIPT_DIR/process_sticker_sheet.py" "$SHEET"

echo ""
echo "Done! Now:"
echo "  1. Open Clawd on Desk"
echo "  2. Right-click the mascot → Settings → Theme"
echo "  3. Select 'Kitty'"
