#!/bin/bash
# Build the standalone macOS app and a DMG. No Terminal process is needed at runtime.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$(uname -s)" = Darwin ] || { echo "Build this app on macOS." >&2; exit 1; }
# A local Command Line Tools SDK may only ship Swift compatibility libraries
# for this Mac's architecture. Universal builds are an explicit CI/release choice.
WRB_ARCH_SELECTION="${WARROOM_BUILD_ARCHS-native}"
case "$WRB_ARCH_SELECTION" in
  native)
    # This detects Apple Silicon even when Terminal itself runs under Rosetta.
    if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || true)" = 1 ]; then
      WRB_ARCHS=(arm64)
    else
      case "$(uname -m)" in
        arm64) WRB_ARCHS=(arm64) ;;
        x86_64) WRB_ARCHS=(x86_64) ;;
        *) echo "Could not determine this Mac's architecture. Set WARROOM_BUILD_ARCHS to arm64 or x86_64." >&2; exit 1 ;;
      esac
    fi ;;
  universal) WRB_ARCHS=(arm64 x86_64) ;;
  arm64|x86_64) WRB_ARCHS=("$WRB_ARCH_SELECTION") ;;
  *) echo "WARROOM_BUILD_ARCHS must be native, universal, arm64 or x86_64." >&2; exit 1 ;;
esac
echo "Building architectures: ${WRB_ARCHS[*]} (selection: $WRB_ARCH_SELECTION)"
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
  local outputs=()
  for arch in "${WRB_ARCHS[@]}"; do
    xcrun --sdk macosx swiftc -swift-version 5 -O -sdk "$WRB_SDK" \
      -target "$arch-apple-macos12.0" "$source" -o "$BUILD_TMP/$name.$arch"
    outputs+=("$BUILD_TMP/$name.$arch")
  done
  if [ "${#outputs[@]}" -eq 1 ]; then
    cp "${outputs[0]}" "$WRB_APP/Contents/MacOS/$name"
  else
    xcrun lipo -create "${outputs[@]}" -output "$WRB_APP/Contents/MacOS/$name"
  fi
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
python3 tools/check_app_ui.py "$WRB_APP"
mkdir -p "$BUILD_TMP/image"
ditto "$WRB_APP" "$BUILD_TMP/image/War Room Bot.app"
ln -s /Applications "$BUILD_TMP/image/Applications"
cp app/DMG-README.txt "$BUILD_TMP/image/README.txt"
WRB_DMG="$DEST/War-Room-Bot-$(cat VERSION).dmg"
hdiutil create -ov -volname "War Room Bot" -srcfolder "$BUILD_TMP/image" -format UDZO "$WRB_DMG"
hdiutil verify "$WRB_DMG"
echo "Built $WRB_DMG (architectures: ${WRB_ARCHS[*]}; bundle identifier $WRB_APP_ID)"
