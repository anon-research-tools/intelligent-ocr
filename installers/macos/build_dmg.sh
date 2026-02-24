#!/bin/bash
# Build macOS DMG installer for 智能 OCR 工具
# Requires: create-dmg (brew install create-dmg) [optional but recommended]
#
# Usage:
#   ./build_dmg.sh          # Build from PyInstaller output
#   ./build_dmg.sh --sign   # Build and sign with ad-hoc signature
#   ./build_dmg.sh --sign "Developer ID Application: Your Name"  # Sign with certificate

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$PROJECT_DIR/dist"
RESOURCES_DIR="$PROJECT_DIR/desktop/resources"
APP_NAME="智能OCR工具"
VERSION="2.2.1"

# Detect architecture of the built app binary
APP_BINARY="$DIST_DIR/$APP_NAME.app/Contents/MacOS/$APP_NAME"
if [ -f "$APP_BINARY" ]; then
    ARCH_RAW=$(file "$APP_BINARY" | grep -oE 'arm64|x86_64|universal' | head -1)
    case "$ARCH_RAW" in
        arm64)   ARCH_LABEL="arm64" ;;
        x86_64)  ARCH_LABEL="intel" ;;
        universal) ARCH_LABEL="universal" ;;
        *)       ARCH_LABEL="$(uname -m)" ;;
    esac
else
    ARCH_LABEL="$(uname -m)"
fi

DMG_NAME="${APP_NAME}_macOS_${ARCH_LABEL}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Building macOS DMG installer...${NC}"
echo "Project directory: $PROJECT_DIR"
echo "Version: $VERSION"

# Parse arguments
SIGN_APP=false
SIGN_IDENTITY="-"  # ad-hoc signature by default

while [[ $# -gt 0 ]]; do
    case $1 in
        --sign)
            SIGN_APP=true
            if [[ -n "$2" && ! "$2" =~ ^-- ]]; then
                SIGN_IDENTITY="$2"
                shift
            fi
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Check if app bundle exists
if [ ! -d "$DIST_DIR/$APP_NAME.app" ]; then
    echo -e "${RED}Error: App bundle not found at $DIST_DIR/$APP_NAME.app${NC}"
    echo "Please run PyInstaller first:"
    echo "  cd $PROJECT_DIR && pyinstaller ocr_tool.spec"
    exit 1
fi

# Verify icon exists
if [ ! -f "$RESOURCES_DIR/icon.icns" ]; then
    echo -e "${YELLOW}Warning: Icon file not found at $RESOURCES_DIR/icon.icns${NC}"
    echo "DMG will be created without custom volume icon."
fi

# Code signing (optional)
if [ "$SIGN_APP" = true ]; then
    echo ""
    echo -e "${GREEN}Signing application...${NC}"
    codesign --deep --force --sign "$SIGN_IDENTITY" "$DIST_DIR/$APP_NAME.app"
    echo "Signed with identity: $SIGN_IDENTITY"
fi

# Create DMG
cd "$DIST_DIR"

# Remove existing DMG files
rm -f "${DMG_NAME}.dmg" "${DMG_NAME}_v${VERSION}.dmg"

echo ""
echo -e "${GREEN}Creating DMG...${NC}"

# Use create-dmg if available (produces nicer DMGs)
if command -v create-dmg &> /dev/null; then
    echo "Using create-dmg..."

    CREATE_DMG_ARGS=(
        --volname "$APP_NAME"
        --window-pos 200 120
        --window-size 660 400
        --icon-size 100
        --icon "$APP_NAME.app" 180 200
        --hide-extension "$APP_NAME.app"
        --app-drop-link 480 200
    )

    # Add volume icon if exists
    if [ -f "$RESOURCES_DIR/icon.icns" ]; then
        CREATE_DMG_ARGS+=(--volicon "$RESOURCES_DIR/icon.icns")
    fi

    # Add background image if exists
    if [ -f "$SCRIPT_DIR/dmg_background.png" ]; then
        CREATE_DMG_ARGS+=(--background "$SCRIPT_DIR/dmg_background.png")
    fi

    create-dmg "${CREATE_DMG_ARGS[@]}" \
        "${DMG_NAME}_v${VERSION}.dmg" \
        "$APP_NAME.app"

else
    echo "create-dmg not found. Creating simple DMG with hdiutil..."
    echo -e "${YELLOW}Tip: Install create-dmg for nicer DMGs: brew install create-dmg${NC}"

    # Create temporary directory for DMG contents
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf '$TEMP_DIR'" EXIT

    cp -R "$APP_NAME.app" "$TEMP_DIR/"
    ln -s /Applications "$TEMP_DIR/Applications"

    # Create DMG
    hdiutil create \
        -volname "$APP_NAME" \
        -srcfolder "$TEMP_DIR" \
        -ov \
        -format UDZO \
        "${DMG_NAME}_v${VERSION}.dmg"
fi

# Verify DMG was created
if [ -f "${DMG_NAME}_v${VERSION}.dmg" ]; then
    DMG_SIZE=$(du -h "${DMG_NAME}_v${VERSION}.dmg" | cut -f1)
    echo ""
    echo -e "${GREEN}✓ DMG created successfully!${NC}"
    echo "  File: $DIST_DIR/${DMG_NAME}_v${VERSION}.dmg"
    echo "  Size: $DMG_SIZE"
else
    echo -e "${RED}Error: DMG creation failed${NC}"
    exit 1
fi

# Sign DMG if requested
if [ "$SIGN_APP" = true ]; then
    echo ""
    echo "Signing DMG..."
    codesign --sign "$SIGN_IDENTITY" "${DMG_NAME}_v${VERSION}.dmg"
    echo "DMG signed."
fi

echo ""
echo -e "${GREEN}Done!${NC}"
echo ""
echo "Architecture: $ARCH_LABEL"
echo "Minimum macOS: 12.0 (Monterey)"
echo ""
echo "Next steps:"
echo "  1. Test the DMG by double-clicking it"
echo "  2. Drag the app to Applications folder"
echo "  3. Launch the app and verify it works"
echo ""
if [ "$ARCH_LABEL" = "arm64" ]; then
    echo -e "${YELLOW}Note: This build requires Apple Silicon (M1/M2/M3/M4).${NC}"
    echo "      Intel Mac users can run it via Rosetta 2:"
    echo "      softwareupdate --install-rosetta"
    echo ""
fi
echo "For distribution:"
echo "  - Consider notarizing with: xcrun notarytool submit ${DMG_NAME}_v${VERSION}.dmg"
echo "  - Or use ad-hoc signing for local testing"
