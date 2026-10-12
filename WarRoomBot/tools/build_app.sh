#!/bin/bash
# Build an unsigned macOS app and DMG from a clean payload.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$(uname -s)" = Darwin ] || { echo "Build this app on macOS." >&2; exit 1; }
ROOT="$PWD"
DEST="${1:-$ROOT/dist}"
mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd -P)"
BUILD_TMP=$(mktemp -d)
trap 'rm -rf "$BUILD_TMP"' EXIT
python3 tools/package.py "$BUILD_TMP/payload.zip"
unzip -q "$BUILD_TMP/payload.zip" -d "$BUILD_TMP"
osacompile -o "$BUILD_TMP/War Room Bot.app" app/WarRoomBot.applescript
mkdir -p "$BUILD_TMP/War Room Bot.app/Contents/Resources/payload"
ditto "$BUILD_TMP/WarRoomBot" "$BUILD_TMP/War Room Bot.app/Contents/Resources/payload"
# Ad-hoc signing is local integrity signing, not Developer ID notarization.
codesign --force --deep --sign - "$BUILD_TMP/War Room Bot.app"
codesign --verify --deep --strict "$BUILD_TMP/War Room Bot.app"
mkdir -p "$BUILD_TMP/image"
ditto "$BUILD_TMP/War Room Bot.app" "$BUILD_TMP/image/War Room Bot.app"
ln -s /Applications "$BUILD_TMP/image/Applications"
cp app/DMG-README.txt "$BUILD_TMP/image/README.txt"
cp app/Start-War-Room-Bot.command "$BUILD_TMP/image/Start-War-Room-Bot.command"
chmod +x "$BUILD_TMP/image/Start-War-Room-Bot.command"
hdiutil create -volname "War Room Bot" -srcfolder "$BUILD_TMP/image" -format UDZO \
  "$DEST/War-Room-Bot-$(cat VERSION).dmg"
echo "Built DMG in $DEST"
