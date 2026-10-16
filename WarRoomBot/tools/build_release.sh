#!/bin/bash
# Build one complete, clean release folder on macOS for sharing with other Macs.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$(uname -s)" = Darwin ] || { echo "Build the native release on macOS." >&2; exit 1; }

WRB_VERSION=$(cat VERSION)
[[ "$WRB_VERSION" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || {
  echo "VERSION is not a safe release name." >&2; exit 1;
}
WRB_RELEASE_ROOT="${1:-$PWD/dist}"
mkdir -p "$WRB_RELEASE_ROOT"
WRB_RELEASE_ROOT=$(cd "$WRB_RELEASE_ROOT" && pwd -P)
WRB_RELEASE="$WRB_RELEASE_ROOT/WarRoomBot-$WRB_VERSION"
[ ! -e "$WRB_RELEASE" ] && [ ! -L "$WRB_RELEASE" ] || {
  echo "Release folder already exists: $WRB_RELEASE" >&2; exit 1;
}

WRB_STAGE=$(mktemp -d "$WRB_RELEASE_ROOT/.warroombot-$WRB_VERSION.XXXXXXXX")
trap 'rm -rf "$WRB_STAGE"' EXIT
WRB_SOURCE="WarRoomBot-$WRB_VERSION-source.zip"
WRB_APP_ZIP="War-Room-Bot-$WRB_VERSION-app.zip"
WRB_DMG="War-Room-Bot-$WRB_VERSION.dmg"

# The source packager uses an allowlist: it excludes .env, roster, logs, venv,
# and files belonging to the machine used to build the release.
python3 tools/package.py "$WRB_STAGE/$WRB_SOURCE"
# A shared build must use a deliberate fleet identifier, never silently adopt
# the identifier of this builder Mac's installed app.
export WARROOM_BUNDLE_ID="${WARROOM_BUNDLE_ID:-com.equinix.warroombot}"
export WARROOM_BUILD_ARCHS="${WARROOM_BUILD_ARCHS:-universal}"
bash tools/build_app.sh "$WRB_STAGE"

for WRB_FILE in "$WRB_SOURCE" "$WRB_APP_ZIP" "$WRB_DMG"; do
  [ -s "$WRB_STAGE/$WRB_FILE" ] || {
    echo "Release build is missing $WRB_FILE." >&2; exit 1;
  }
done
(
  cd "$WRB_STAGE"
  shasum -a 256 "$WRB_SOURCE" "$WRB_APP_ZIP" "$WRB_DMG" > SHA256SUMS.txt
  shasum -a 256 -c SHA256SUMS.txt
)
mv "$WRB_STAGE" "$WRB_RELEASE"
echo "Complete release: $WRB_RELEASE"
echo "Share the DMG and SHA256SUMS.txt for a new installation."
echo "Keep the source ZIP and app ZIP with the release for source review and verified app updates."
