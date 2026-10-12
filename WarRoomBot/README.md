# Zoom war-room bot for macOS

Watches a Zoom meeting (the "bridge") from the Zoom desktop app. When someone who is not support joins, it:

1. plays a spoken welcome **into the meeting** as Zoom shared "Computer audio", and
2. in parallel, calls the on-duty engineer into the meeting by phone (Invite → Zoom Phone → Call → Complete meeting invite),
3. writes a row to `logs/join_log.csv`.

It drives the Zoom app through macOS Accessibility. It does not use the Zoom API, so it needs a Mac that stays awake, unlocked and signed in to Zoom as the bot account, with the bridge meeting open.

**Out of the box it can only dial YOUR phone** (test mode). Calling the real roster is a separate, deliberate switch described in `MAC_SETUP.md`.

## Build and install the Mac app

This release includes source files. A prebuilt DMG is not included. On your Mac, extract the ZIP, open Terminal in the `WarRoomBot` folder, and run `bash tools/build_app.sh`. The DMG is created at `dist/War-Room-Bot-20261012.5.dmg`. See the terminal install below for prerequisites.

Then:

1. Open the DMG and drag **War Room Bot** onto **Applications**. Open it from there.
2. macOS will probably say it "cannot be opened" because the app has no Apple Developer ID. Open **System Settings → Privacy & Security**, scroll down, click **Open Anyway** next to "War Room Bot", and confirm. (Or run `xattr -dr com.apple.quarantine "/Applications/War Room Bot.app"` once in Terminal.) A Mac managed by IT may not allow this; use the terminal install below instead.
3. First launch asks to **set up** (about 2 minutes: files go to `~/WarRoomBot`, packages come from Nexus, so be on the Equinix network or VPN; if the Apple developer tools are missing macOS offers to install them, then open the app again).
4. Switch on **War Room Bot** under **System Settings → Privacy & Security → Accessibility** (the app opens that page), then enter your **test phone number**.
5. Sign Zoom in as the bot account, join the bridge meeting, and use the menu: **Check** (read-only), **Dry run**, **Start** (test mode: calls only your number), **Stop**, **Status**, **Recent activity**.

The watcher runs in the background and keeps running after you quit the app; open the app and choose **Stop** to switch it off. Roster, `.env` and logs are in `~/WarRoomBot` (**Open data folder**). **Update / Repair** re-runs set-up and keeps those files. After installing a newer version of the app, switch it off and on again in the Accessibility list.

The app is a thin menu around `app/wrb.sh`, so everything it does also works by hand: `/bin/bash app/wrb.sh status`, `start`, `stop`, `set-number +1…` (run it with no arguments for the list).

## Install from the zip (terminal)

Needs macOS, Python 3.9+ and the Xcode command line tools (`xcode-select --install`). Dependencies come from the Equinix Nexus PyPI mirror only, with hashes checked, so be on the Equinix network or VPN.

```bash
unzip WarRoomBot-fixed-20261012.5.zip
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

Your `.env`, `roster.xlsx`, `logs/` and the compiled `tools/axctl` are private to each install and are created by `./install.sh` (or by the app's set-up). Build a clean zip with `python3 tools/package.py dist/WarRoomBot.zip`. On a Mac, build an unsigned app DMG with `bash tools/build_app.sh`. Both scripts are included. See `BUILD_NOTES.md` for the fixes, verification and remaining Mac checks.

## If Accessibility stays blocked

The Terminal and app launch paths can have different permissions. In Terminal, run `"$HOME/WarRoomBot/tools/axctl" trusted`. If the result is `{"ok":false}`, enable Terminal under System Settings → Privacy & Security → Accessibility, fully quit Terminal and reopen it before checking again. When the result is `{"ok":true}`, run `cd "$HOME/WarRoomBot"`, then `./watch.sh check` and `./watch.sh dry` to verify the meeting through Terminal.

A successful Terminal check does not establish the app grant. In the app, use **Show diagnostics** after a failed permission check to obtain the result from that app launch. Do not keep rebuilding the helper after granting it permission; rebuilds can change its code signature. See `BUILD_NOTES.md` for the Mac validation limits.


## Launch the app through Terminal

If the app helper reports denied access from a normal app launch but succeeds from Terminal, quit War Room Bot and double-click `app/Start-War-Room-Bot.command`. It opens the installed `/Applications/War Room Bot.app` through Terminal and leaves watcher controls in the app menu. Keep that Terminal window open while using the app. The shortcut does not start the watcher or change your settings.

Directly launching the installed app executable from Terminal reached the normal menu on the target Mac with version 20261012.4. This confirms that launch path passed the app's permission check. It does not repair normal Finder/Dock launch; Check and background Dry run from this menu still need to be verified on the target Mac.
