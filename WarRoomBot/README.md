# Zoom war-room bot for macOS

Watches a Zoom meeting (the "bridge") from the Zoom desktop app. When someone who is not support joins, it:

1. plays a spoken welcome **into the meeting** as Zoom shared "Computer audio", and
2. in parallel, calls the on-duty engineer into the meeting by phone (Invite → Zoom Phone → Call → Complete meeting invite),
3. writes a row to `logs/join_log.csv`.

It drives the Zoom app through macOS Accessibility. It does not use the Zoom API, so it needs a Mac that stays awake, unlocked and signed in to Zoom as the bot account, with the bridge meeting open.

**Out of the box it can only dial YOUR phone** (test mode). Calling the real roster is a separate, deliberate switch described in `MAC_SETUP.md`.

## Install as an app (easiest)

Get `War-Room-Bot-<version>.dmg` (built with `tools/build_app.sh`), then:

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
unzip WarRoomBot-fixed-20261012.1.zip
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
| `./watch.sh check` | Read-only. Shows the meeting window and who is in it. Start here. |
| `./watch.sh dry` | Watches and logs what it would do. Nothing is dialled or played. |
| `./watch.sh start` | Live, test mode: a new visitor makes it call your test number and play the welcome. |
| `./watch.sh status` | `ON` or `OFF`. |
| `./watch.sh stop` | Switch it off (or press Ctrl-C in its window). |

Check what happened in `logs/join_log.csv` (`welcome_voice` is `yes` when the welcome played; `engineer_called` and `call_answered` show the call).

## Things to know

* The Mac must be awake and **unlocked**; a locked screen is untested and probably fails. `watch.sh` keeps the Mac awake with `caffeinate`.
* Run it in the same Space/desktop as the meeting, or keep the meeting where Accessibility can see it. A full-screen meeting on another Space is invisible until you switch to it.
* While the welcome plays, the bot shares computer audio, which everyone in the meeting can see ("Presenting"). Run `voice-test` only when you can click the share's x yourself.
* Optional, off by default: `WARROOM_ZOOM_INVITE=true` also invites the engineer as a Zoom contact (Invite → Contacts). In test mode it needs `WARROOM_TEST_ZOOM_EMAIL`. Not yet run live; see `MAC_SETUP.md` section 7c.
* Safety gates all fail closed: `WARROOM_DRY_RUN`, `WARROOM_LIVE_CALLING`, `WARROOM_TARGET_MODE`, `WARROOM_ALLOW_ROSTER_CALLS`. Details and every setting are in `MAC_SETUP.md` and `.env.example`.
* Tests: `.venv/bin/python -m pytest -q` (they never touch Zoom).

## What is not in this package

Your `.env`, `roster.xlsx`, `logs/` and the compiled `tools/axctl` are private to each install and are created by `./install.sh` (or by the app's set-up). Build a clean zip with `python3 tools/package.py dist/WarRoomBot.zip`. On a Mac, build an unsigned app DMG with `bash tools/build_app.sh`. Both scripts are included. See `BUILD_NOTES.md` for the fixes, verification and remaining Mac checks.
