# Zoom war-room bot for macOS

Watches a Zoom meeting (the "bridge") from the Zoom desktop app. When someone who is not support joins, it:

1. plays a spoken welcome **into the meeting** as Zoom shared "Computer audio", and
2. in parallel, calls the on-duty engineer into the meeting by phone (Invite → Zoom Phone → Call → Complete meeting invite),
3. writes a row to `logs/join_log.csv`.

It drives the Zoom app through macOS Accessibility. It does not use the Zoom API, so it needs a Mac that stays awake, unlocked and signed in to Zoom as the bot account, with the bridge meeting open.

**Start: test number** calls only your configured test phone. **Start: roster** is a separate action that previews the on-duty engineer and asks you to confirm real roster calls.

## Build and install the Mac app

The macOS build workflow produces a universal app and DMG for Apple Silicon and Intel. To build locally, extract the source ZIP, open Terminal in the extracted `WarRoomBot` folder, and run `bash tools/build_app.sh`. Local builds select your Mac's native architecture; an M3 Pro builds `arm64`. Universal builds require `WARROOM_BUILD_ARCHS=universal` and an SDK containing both architectures' Swift libraries. The DMG is created at `dist/War-Room-Bot-20261012.6.dmg`. Terminal is used for a local build, not for running the installed native app.

Then:

1. Stop an existing watcher before replacing the app. Open the DMG and drag **War Room Bot** onto **Applications**. Eject old War Room Bot disk images and open the installed `/Applications/War Room Bot.app`.
2. macOS will probably say it "cannot be opened" because the app has no Apple Developer ID. Open **System Settings → Privacy & Security**, scroll down, click **Open Anyway** next to "War Room Bot", and confirm. (Or run `xattr -dr com.apple.quarantine "/Applications/War Room Bot.app"` once in Terminal.) A Mac managed by IT may not allow this; use the terminal install below instead.
3. Use **Set up / Update / Repair** in the native window. Files go to `~/WarRoomBot`, packages come from Nexus, and tests must pass. The inline progress display clears after setup finishes.
4. Use **Request Accessibility permission** once to request the macOS permission dialog, or **Open Accessibility Settings** to open the pane. These are separate actions. Enable the installed app. **Diagnostics** reports the native app's permission, bundled helper permission, identifier and exact paths separately.
5. Sign Zoom in as the bot account and join the bridge. Use **Check meeting**, then **Dry run: test number**, before **Start: test number**. Enter your test phone with **Change test phone number**.
6. For roster calls, put real shifts and international phone numbers in `~/WarRoomBot/roster.xlsx`. Use **Preview on-duty roster**, then **Dry run: roster**, then **Start: roster**. Live roster start refuses an absent or invalid on-duty target and requires confirmation. The lowest priority number is selected; there is no automatic fallback to the next engineer.

Closing the native window hides it while the watcher runs; reopen it from the Dock or the War Room Bot status item. **Quit** offers **Stop and quit**, **Hide and keep watching**, or **Cancel**. The native app stays running when hidden so its worker retains the app's launch context. Terminal can be closed. Roster, `.env` and logs remain in `~/WarRoomBot` (**Open data folder**); **Update / Repair** preserves them. This build keeps the app name and data path and declares a stable bundle identifier. macOS/IT can still require a grant for changed signed code.

If the downloaded app and bundled helper both hang before producing output, while `~/WarRoomBot/tools/axctl trusted` works, a local rebuild provides a useful comparison. Run `bash tools/rebuild_installed_app.sh` from a source checkout, or download that script and run it with Bash. It copies the source embedded in `/Applications/War Room Bot.app` into a private temporary folder, compiles with your Mac's tools, preserves the installed identifier and opens the resulting DMG. Replace the app through Finder afterward. Existing settings and roster remain in their data folder. The build has a five-minute deadline and prints the recent build output on failure; Terminal is used for rebuilding, not normal app operation. Local compilation is not proof that a particular execution-policy issue is fixed.

The native window controls `app/wrb.sh` through direct child processes. Manual commands include `status`, `start`, `dry`, `roster-preview`, `roster-start`, `roster-dry`, `stop` and `set-number +1…`.

## Install from the zip (terminal)

Needs macOS, Python 3.9+ and the Xcode command line tools (`xcode-select --install`). Dependencies come from the Equinix Nexus PyPI mirror only, with hashes checked, so be on the Equinix network or VPN.

```bash
unzip WarRoomBot-fixed-20261012.6.zip
cd WarRoomBot
chmod +x install.sh watch.sh tools/*.sh app/wrb.sh
./install.sh
```

The installer builds the Accessibility helper, creates `.env` and a placeholder `roster.xlsx`, and runs the tests. Then, by hand:

1. **System Settings → Privacy & Security → Accessibility**: switch on the app you run the bot from (Terminal, iTerm or Claude), then quit and reopen it.
2. **`.env`**: set `WARROOM_TEST_NUMBER=+<country code><number>` to a phone you control.
3. Sign Zoom in as the bot account and join the bridge meeting.

## Use

| Command | What it does |
|---|---|
| `./watch.sh check` | Shows the meeting window and who is in it. Brings Zoom forward if the meeting is hidden; never calls or shares audio. Start here. |
| `./watch.sh dry` | Watches and logs what it would do. Nothing is dialled or played. |
| `./watch.sh start` | Live, test mode: a new visitor makes it call your test number and play the welcome. |
| `./watch.sh roster-preview` | Read-only: reports the selected on-duty engineer and checks the phone number. |
| `./watch.sh roster-dry` | Watches roster selection; nothing is dialled or played. |
| `./watch.sh roster` | Live roster calls to the current highest-priority on-duty engineer. |
| `./watch.sh status` | `ON` or `OFF`. |
| `./watch.sh stop` | Requests graceful shutdown of this install's Python watcher. Check Status for `OFF`, or press Ctrl-C in its window. |

Check what happened in `logs/join_log.csv` (`welcome_voice` is `yes` when the welcome played; `engineer_called` and `call_answered` show the call).

Status and Stop use the actual Python worker's PID and a fresh launch token. `caffeinate` observes that worker and exits with it; it is not the process Stop signals. The app waits up to 20 seconds for shutdown. If cleanup takes longer, it reports "still stopping" and points to `logs/watcher.log`. Active shared welcomes finish or cancel before the worker releases its process record. A direct `python -m warroom.cli watch` started without `watch.sh` remains controlled with Ctrl-C in its Terminal window.

## Things to know

* The Mac must be awake and **unlocked**; a locked screen is untested and probably fails. `watch.sh` keeps the Mac awake with `caffeinate`.
* Check and watcher startup try to bring Zoom forward once if a full-screen meeting is hidden on another Space. Minimized windows that Accessibility exposes remain readable. During polling the watcher does not take focus; if macOS hides the meeting again, it waits until the window is exposed.
* While the welcome plays, the bot shares computer audio, which everyone in the meeting can see ("Presenting"). Run `voice-test` only when you can click the share's x yourself.
* Optional, off by default: `WARROOM_ZOOM_INVITE=true` also invites the engineer as a Zoom contact (Invite → Contacts). In test mode it needs `WARROOM_TEST_ZOOM_EMAIL`. Not yet run live; see `MAC_SETUP.md` section 7c.
* Safety gates all fail closed: `WARROOM_DRY_RUN`, `WARROOM_LIVE_CALLING`, `WARROOM_TARGET_MODE`, `WARROOM_ALLOW_ROSTER_CALLS`. Details and every setting are in `MAC_SETUP.md` and `.env.example`.
* Tests: `.venv/bin/python -m pytest -q` (they never touch Zoom).

## What is not in this package

Your `.env`, `roster.xlsx`, `logs/` and virtual environment are private to each install. Source ZIPs exclude compiled helpers; the native DMG contains a newly compiled, signed helper inside the app. Terminal uses the separately installed `tools/axctl`. Build a clean ZIP with `python3 tools/package.py dist/WarRoomBot.zip`, or a DMG with `bash tools/build_app.sh`. IT can supply `WARROOM_BUNDLE_ID` and a local `WARROOM_SIGN_IDENTITY`; credentials are never included. See `BUILD_NOTES.md` for verification and remaining Mac checks.

## If Accessibility stays blocked

Use **Diagnostics** in the installed native app. Its helper should be `/Applications/War Room Bot.app/Contents/MacOS/axctl`. The app checks its own permission and the helper's result; both must pass before Start. A successful Terminal check does not establish app access because Terminal uses a separate launch context and the data-folder helper.

Eject old disk images and quit older app copies before testing the installed app. Mounted copies can make app selection and permission entries ambiguous. The permission request is asynchronous; allowing it does not change the result of a check already in progress. Recheck through the native window. See `BUILD_NOTES.md` for the remaining target-Mac validation.


## Older AppleScript app builds

Versions through 20261012.5 used an AppleScript menu and an external installed helper. `app/Start-War-Room-Bot.command` is retained only as a diagnostic workaround for those older builds; it is not required by the native app and is not included in the new DMG.

The target Mac completed version 20261012.5 setup with all 429 tests passing. Native app permissions, Check, Dry run and operation while hidden still require testing on that Mac; compilation and mocked tests do not establish those grants or live call behavior.
