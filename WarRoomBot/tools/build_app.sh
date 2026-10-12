#!/bin/bash
# Build the standalone macOS app and a DMG. No Terminal process is needed at runtime.
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
WRB_APP="$BUILD_TMP/War Room Bot.app"
mkdir -p "$WRB_APP/Contents/MacOS" "$WRB_APP/Contents/Resources/payload"
ditto "$BUILD_TMP/WarRoomBot" "$WRB_APP/Contents/Resources/payload"

# Keep the installed identifier when building an update locally. IT can supply
# an explicit identifier and keychain signing identity without saving credentials.
WRB_APP_ID=$(python3 - <<'PY'
import os
import plistlib
import re
import sys
from pathlib import Path
identifier = os.environ.get('WARROOM_BUNDLE_ID', '')
if not identifier:
    existing = Path(os.environ.get('WARROOM_EXISTING_APP', '/Applications/War Room Bot.app'))
    try:
        with (existing / 'Contents/Info.plist').open('rb') as stream:
            identifier = plistlib.load(stream).get('CFBundleIdentifier', '')
    except (OSError, plistlib.InvalidFileException, ValueError):
        pass
identifier = identifier or 'com.equinix.warroombot'
if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{2,254}', identifier):
    print('Invalid app bundle identifier.', file=sys.stderr)
    sys.exit(1)
print(identifier)
PY
)
python3 - "$WRB_APP/Contents/Info.plist" "$WRB_APP_ID" "$(cat VERSION)" <<'PY'
import plistlib
import sys
with open(sys.argv[1], 'wb') as stream:
    plistlib.dump({
        'CFBundleName': 'War Room Bot',
        'CFBundleDisplayName': 'War Room Bot',
        'CFBundleIdentifier': sys.argv[2],
        'CFBundleExecutable': 'WarRoomBot',
        'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': sys.argv[3],
        'CFBundleVersion': sys.argv[3],
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',
    }, stream)
PY
WRB_SDK=$(xcrun --sdk macosx --show-sdk-path)
compile_universal() {
  local source="$1" name="$2" arch
  for arch in arm64 x86_64; do
    xcrun --sdk macosx swiftc -swift-version 5 -O -sdk "$WRB_SDK" \
      -target "$arch-apple-macos12.0" "$source" -o "$BUILD_TMP/$name.$arch"
  done
  xcrun lipo -create "$BUILD_TMP/$name.arm64" "$BUILD_TMP/$name.x86_64" \
    -output "$WRB_APP/Contents/MacOS/$name"
}
compile_universal app/WarRoomBot.swift WarRoomBot
compile_universal tools/axctl.swift axctl
# Sign nested code before its containing app. '-' is ad-hoc integrity signing.
WRB_SIGN_IDENTITY="${WARROOM_SIGN_IDENTITY:--}"
codesign --force --sign "$WRB_SIGN_IDENTITY" --identifier "$WRB_APP_ID.axctl" \
  "$WRB_APP/Contents/MacOS/axctl"
codesign --force --sign "$WRB_SIGN_IDENTITY" --identifier "$WRB_APP_ID" "$WRB_APP"
codesign --verify --deep --strict "$WRB_APP"
"$WRB_APP/Contents/MacOS/WarRoomBot" --smoke-test
mkdir -p "$BUILD_TMP/image"
ditto "$WRB_APP" "$BUILD_TMP/image/War Room Bot.app"
ln -s /Applications "$BUILD_TMP/image/Applications"
cp app/DMG-README.txt "$BUILD_TMP/image/README.txt"
WRB_DMG="$DEST/War-Room-Bot-$(cat VERSION).dmg"
hdiutil create -ov -volname "War Room Bot" -srcfolder "$BUILD_TMP/image" -format UDZO "$WRB_DMG"
hdiutil verify "$WRB_DMG"
echo "Built $WRB_DMG (Apple Silicon and Intel; bundle identifier $WRB_APP_ID)"
