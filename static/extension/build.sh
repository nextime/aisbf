#!/bin/bash
# Build script for AISBF OAuth2 Redirect Extension
# Creates a packaged ZIP file ready for distribution

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/.."
OUTPUT_FILE="$OUTPUT_DIR/aisbf-oauth2-extension.zip"

echo "Building AISBF OAuth2 Redirect Extension..."
echo "Source directory: $SCRIPT_DIR"
echo "Output file: $OUTPUT_FILE"

# Remove old ZIP if it exists
if [ -f "$OUTPUT_FILE" ]; then
    echo "Removing old package..."
    rm "$OUTPUT_FILE"
fi

# Create ZIP file
echo "Creating package..."
cd "$SCRIPT_DIR"
zip -r "$OUTPUT_FILE" \
    manifest.json \
    background.js \
    content.js \
    inject_marker.js \
    popup.html \
    popup.js \
    options.html \
    options.js \
    README.md \
    icons/ \
    -x "*.sh" "*.md~" "*~" ".DS_Store"

echo ""
echo "✓ Extension packaged successfully!"
echo "Package location: $OUTPUT_FILE"
echo ""
echo "To install:"
echo "1. Extract the ZIP file"
echo "2. Open Chrome and go to chrome://extensions/"
echo "3. Enable 'Developer mode'"
echo "4. Click 'Load unpacked'"
echo "5. Select the extracted folder"
