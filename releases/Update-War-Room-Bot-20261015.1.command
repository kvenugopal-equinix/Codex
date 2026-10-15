#!/bin/bash
# Run from Terminal with the matching source ZIP in this file's folder.
set -euo pipefail

WRB_FOLDER=$(cd "$(dirname "$0")" && pwd -P)
WRB_ZIP="$WRB_FOLDER/WarRoomBot-20261015.1-source.zip"
WRB_SHA256=0e567d4ec6f6927f1879a4ec78cc46455d4a04e15fab436b381f55fdb50995fc

if [ ! -f "$WRB_ZIP" ]; then
  echo "Place WarRoomBot-20261015.1-source.zip beside this launcher." >&2
  exit 1
fi

WRB_ACTUAL=$(/usr/bin/shasum -a 256 "$WRB_ZIP")
WRB_ACTUAL=${WRB_ACTUAL%% *}
if [ "$WRB_ACTUAL" != "$WRB_SHA256" ]; then
  echo "The source ZIP checksum does not match. No update was started." >&2
  exit 1
fi

WRB_STAGE=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/warroom-runtime-update.XXXXXXXX")
cleanup() {
  if [ -n "${WRB_STAGE:-}" ] && [ -d "$WRB_STAGE" ]; then
    /bin/rm -rf "$WRB_STAGE"
  fi
}
trap cleanup EXIT

/usr/bin/unzip -q "$WRB_ZIP" -d "$WRB_STAGE"
echo "Source ZIP verified. Updating the installed Python runtime..."
/usr/bin/python3 -u "$WRB_STAGE/WarRoomBot/tools/apply_activity_runtime_update.py" \
  --archive "$WRB_ZIP" --sha256 "$WRB_SHA256" --choose-workbook
