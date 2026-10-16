# Complete War Room Bot build for other Macs

This source version is `20261015.1`. It contains the native **Choose log file…** control, the Python activity workbook writer, and the normal bot runtime. The current release worktree has source code only; the DMG must be compiled and checked on macOS before it can be shared as an app.

## Build one complete release

On a Mac with Xcode Command Line Tools and Python 3.9 or newer, open Terminal in the `WarRoomBot` source folder and run:

```bash
WARROOM_BUILD_ARCHS=universal bash tools/build_release.sh
```

The result is `dist/WarRoomBot-20261015.1/` with:

| File | Use |
|---|---|
| `War-Room-Bot-20261015.1.dmg` | Complete app for a new user to install through Finder. Includes the native window, compiled Accessibility helper, and clean Python source payload. |
| `War-Room-Bot-20261015.1-app.zip` | Complete signed app for the verified Finder replacement procedure (`tools/prepare_app_update.py`). |
| `WarRoomBot-20261015.1-source.zip` | Clean source, setup scripts, tests, and build instructions; no personal settings, roster, log, or virtual environment. |
| `SHA256SUMS.txt` | SHA-256 digest of each of the three files above. Keep this next to the files you share. |

`build_release.sh` creates the source ZIP from an allowlist, compiles the app and helper, signs and checks the app, runs its smoke and UI checks, verifies the DMG, and checks its own hashes. By default it selects both Apple Silicon and Intel architectures and uses the fleet bundle identifier `com.equinix.warroombot`. A Mac whose SDK lacks one architecture's Swift libraries can build for Macs with the same architecture using `WARROOM_BUILD_ARCHS=native`; that result is **not** a universal release. IT can supply `WARROOM_SIGN_IDENTITY` and `WARROOM_BUNDLE_ID` when approved signing and a different fleet identifier are required. Without an IT signing identity, the app uses ad hoc signing and is not notarized.

The release folder must not already exist. Keep all four files together and record the source commit and Mac build result. The GitHub Actions download lasts only 14 days, so copy a verified full release into durable storage before sharing it. A Windows checkout can make and inspect the source ZIP but cannot compile or verify the native DMG. In PowerShell, from the `WarRoomBot` source folder, use the Python launcher if available:

```powershell
py -3 tools/package.py dist/WarRoomBot-20261015.1-source.zip
Get-FileHash dist/WarRoomBot-20261015.1-source.zip -Algorithm SHA256
```

If `py` is unavailable, substitute the path to a Python 3 executable. The source ZIP is not an installed Mac app. The macOS workflow can also build and upload the app artifacts after this branch is pushed and its tests pass.

## Give the full version to someone else

Share the DMG and `SHA256SUMS.txt`; keep the source ZIP and app ZIP available for review and future upgrades. The recipient opens the DMG, drags **War Room Bot** to **Applications**, opens that installed app, then runs **Set up / Update / Repair**. Setup creates the recipient's private `~/WarRoomBot` data folder and installs Python dependencies from the configured Equinix Nexus mirror. It does not copy the builder's `.env`, roster, or logs. The recipient must grant the app Accessibility permission and run the documented dry checks before live use. See [README.md](README.md) and [MAC_SETUP.md](MAC_SETUP.md).

The new native **Choose log file…** button is present in this full build. It can select an `.xlsx` location in a OneDrive or SharePoint library that appears in Finder. The bot creates the workbook there after the path is selected. A cloud location available only through the OneDrive website needs to be synced into Finder first. Concurrent Excel/OneDrive editing of the workbook's Comments while the bot writes has not yet passed a target-Mac acceptance check.

## Update the already installed bot without replacing the app

For the known installed `20261013.3` app, use the release's checked `tools/apply_activity_runtime_update.py` procedure after stopping the watcher and quitting the app. It accepts a source ZIP and its SHA-256 digest, and `--choose-workbook` opens the Mac destination picker during the update. This patches supported Python/runtime files in `~/WarRoomBot` and keeps `/Applications/War Room Bot.app`, its signed helper, installed version display, roster, settings, and logs in place. The complete DMG above is for other users or a later native app upgrade.

Python-only updates cannot add the new button to the existing Swift window. The runtime update's separate Mac dialog chooses a Finder-visible OneDrive location while the bot creates the workbook. Do not use the old app's **Set up / Update / Repair** after a runtime patch unless the patch is reapplied; that action restores its bundled runtime. Follow the exact commands and digest in the published runtime update instructions once that artifact has been built and checked.
