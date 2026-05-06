#!/bin/bash
#
# Build script for macOS .app bundle
# Creates a native macOS application with PyInstaller
#
# Usage:
#   ./build_macos.sh
#
# Output:
#   dist/MedicalRAG.app - macOS application bundle
#   dist/MedicalRAG-v1.0.0.dmg - DMG installer (if create-dmg is installed)
#

set -e  # Exit on error

VERSION="1.0.0"
APP_NAME="MedicalRAG"

echo "=========================================="
echo "Building Medical RAG for macOS"
echo "Version: ${VERSION}"
echo "=========================================="
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found"
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install/upgrade production dependencies
echo "Installing production dependencies..."
pip install --upgrade pip
pip install -r requirements-prod.txt

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build dist *.egg-info

# Run PyInstaller
echo ""
echo "Running PyInstaller..."
pyinstaller build_macos.spec

# Check if build succeeded
if [ ! -d "dist/${APP_NAME}.app" ]; then
    echo ""
    echo "❌ Build failed - .app bundle not found"
    exit 1
fi

echo ""
echo "✅ Build successful!"
echo "   App bundle: dist/${APP_NAME}.app"
echo ""

# Check if create-dmg is available for creating DMG
if command -v create-dmg &> /dev/null; then
    echo "Creating DMG installer..."

    # Create DMG
    create-dmg \
        --volname "${APP_NAME}" \
        --window-pos 200 120 \
        --window-size 800 400 \
        --icon-size 100 \
        --icon "${APP_NAME}.app" 200 190 \
        --hide-extension "${APP_NAME}.app" \
        --app-drop-link 600 185 \
        "dist/${APP_NAME}-v${VERSION}.dmg" \
        "dist/${APP_NAME}.app" || true

    if [ -f "dist/${APP_NAME}-v${VERSION}.dmg" ]; then
        echo ""
        echo "✅ DMG created!"
        echo "   Installer: dist/${APP_NAME}-v${VERSION}.dmg"
    else
        echo ""
        echo "⚠️  DMG creation failed, but .app bundle is ready"
    fi
else
    echo "⚠️  create-dmg not found"
    echo "   Install with: brew install create-dmg"
    echo "   .app bundle is ready to use without DMG"
fi

echo ""
echo "=========================================="
echo "Build Complete!"
echo "=========================================="
echo ""
echo "To test the app:"
echo "  open dist/${APP_NAME}.app"
echo ""
echo "Note: Make sure Ollama is installed:"
echo "  brew install ollama"
echo ""
