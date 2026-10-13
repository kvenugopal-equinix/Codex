# Zoom war-room bot: macOS setup guide

Mac version of `MAC_PORTING.md`. It is a runbook for the Mac, not a list of what differs from Windows.
The Windows source was not available, so the package here (`warroom/`) was rebuilt from the porting notes. The Mac UI layer is `warroom/ui_backend.py`, which drives Zoom through `tools/axctl` (a small Swift Accessibility helper; build it with `tools/build_axctl.sh`).

## 1. What the bot does

A dedicated bot account sits in a fixed Zoom meeting (the "bridge"). When someone other than a support engineer joins, the bot:

1. Posts a short welcome in the meeting chat.
2. Waits a short grace period.
3. Adds the on-duty engineer to the meeting by phone call-out (Invite -> Zoom Phone -> Call -> **Complete meeting invite**).

The engineer comes from `roster.xlsx` (shifts, priorities, time zones). Every join is logged to `logs/join_log.csv`.

## 2. Files in this folder

| File | Purpose |
|---|---|
| `roster.xlsx` | Placeholder roster planner. Sheet `roster` holds the data and sheet `README` explains the columns. Replace the placeholder rows. |
| `logs/join_log.csv` | Header-only log of join events, for reporting. The bot appends one row per join. |
| `README.md` | Short install and usage guide for someone receiving this package. |
| `install.sh` | One-time setup: venv, pinned dependencies from Nexus, builds `tools/axctl`, creates `.env` and a placeholder roster, runs the tests. |
| `watch.sh` | `start` (live, test mode), `dry`, `check`, `stop`, `status`. |
| `tools/package.sh`, `tools/stage_payload.sh`, `tools/build_app.sh` | Maintainer only (not in the shared package): build the zip and the app/DMG from an allowlist, after a personal-data scan. |
| `app/WarRoomBot.applescript`, `app/wrb.sh` | The app's menu, and the control script it calls for every action. |
| `tools/set_env.py` | Sets one allowed `.env` value (test number, test Zoom email, invite switch) in place, validated. |
| `MAC_SETUP.md` | This guide. |

### join_log.csv columns

`joined_at_utc, joined_at_local, timezone, meeting_id, participant_name, participant_id, role, welcome_posted, welcome_voice, engineer_called, engineer_name, call_started_utc, call_answered, notes, zoom_invited`

`zoom_invited` is empty (feature off), `dry-run`, `yes`, `no` or `unknown`. A log written before this column existed is rewritten once with the new header (old rows padded); if that rewrite is not possible, new rows are written under the old header and the column is dropped.

Store UTC for reporting and the local time for readability. Append only; never edit old rows.

## 3. Status

* Verified live only on Windows (Citrix VDA, Zoom VDI 7.0.12).
* macOS: two successful live runs on 2026-10-08 against the test number (`TARGET_MODE=test`), both started by hand with `join`: the bot typed the number in the Invite window, pressed Call, pressed Continue on the audio-switch prompt once, and reported `answered and added to the meeting`. Nothing else has run live. The join watcher (`watch`, section 7a) has read a real participant list, detected a real joiner and placed one real test call by itself (2026-10-09, meeting full screen, `answered and added to the meeting`); its Invite step has also been rehearsed live windowed and minimised (Call never pressed). The spoken welcome was first heard only on this Mac's speakers; it now goes into the meeting as shared computer sound (section 7b), which has been mapped live but not yet heard by a joiner. Roster calls (`TARGET_MODE=roster`) have never been run on the Mac, and the other Zoom names were learned from this one meeting.

## 4. Porting map

### Ports as-is (pure Python)

`config.py`, `roster.py`, `identity.py`, `presence.py`, `engine.py`, `store.py`, `alerting.py`, `webhook.py`, `zoom_api.py`, `simulate.py`, `ui_watcher.py`.

Run `pytest -q` first. On the Mac, treat any failure as a real portability bug.

### Replace for macOS

| Windows file / feature | Windows dependency | Mac replacement |
|---|---|---|
| `ui_backend.py` | `pywinauto`, `win32api`, `winsound` | Accessibility API via `pyobjc` (ApplicationServices / AXUIElement), `atomacos`, or `osascript` + System Events. The app that runs it needs **Accessibility permission** |
| `agent_control.py` | `taskkill`, PowerShell, `DETACHED_PROCESS` | `kill`, `ps -p`, `subprocess.Popen(start_new_session=True)`, or a `launchd` agent |
| `dialer.py`, `joiner.py` | registry URI handlers, `os.startfile` | `subprocess.run(["open", "zoomphonecall://+65..."])` |
| TTS (optional, off by default) | PowerShell `System.Speech`, `winsound` | `say -o file.aiff`, `afplay` |
| `*.cmd` launchers | batch files | `.command` file or `launchd` plist (section 8) |

`requirements.txt` already skips the Windows libraries on a Mac through `sys_platform == "win32"` markers. Packages come from the Equinix Nexus PyPI mirror (`https://nexus.equinix.com/repository/pypi-mirror/simple/`). Do not install from public PyPI.

### UI-layer contract

Keep these names and shapes and nothing else changes:

* `meeting_window()` / `in_meeting()`: raise `UiUnavailable` if there is no meeting.
* `read_participants() -> list[UiParticipant]`: needs `display_name`, `participant_id`, `is_me`, `is_host`, `phone_number`.
* `callout(number, timeout, should_abort=None, *, press_call=False, hold=0.0) -> CalloutResult`.
* `invite_contact(email="", *, contact_name="", press_invite=False) -> InviteResult`: optional, see section 7c. Supply exactly one lookup selector. The app uses `contact_name`; the positional email lookup remains for older configurations. A UI exception means Invite was NOT pressed; an uncertain press returns an `unknown` result.
* `send_chat(message)`.
* `busy` / `exclusive()`: the watcher skips polling while an action runs.
* `input_available()`, `rehearse()`: used by `warroom selftest`.

## 5. Lessons from the Windows client (re-verify each on Mac)

1. Invite -> Zoom Phone -> Call places a separate call. It joins the meeting only after **Complete meeting invite** is pressed, and only once the callee has answered.
2. "Answered" appears as an elapsed-time label. The accessibility text differs from the drawn text (`00:34` on screen, `34 seconds` / `1 minute 5 seconds` in the tree). Match both, anchored, so call-history rows (`Duration:32 seconds`) are not mistaken for a live call.
3. Chat history and participant list are both lists of list items. Read participants only from inside the participant list, or the bot's own greeting is parsed as a person.
4. The bot is always in its own participant list. A read without its own row is a glitch, not an empty room.
5. Find the participant list element once and reuse it. Full-window scans took about 5 s versus about 0.06 s for a warm read.
6. Escape keystrokes. Some input libraries interpret `+` as a modifier instead of a literal character. Always read the phone field back and refuse to press Call if it does not match the user-entered international number.
7. Standard value patterns were rejected on text fields on Windows. On macOS try setting `AXValue` first.
8. After Call, the Invite dialog closes itself. If it is still open, Call did nothing, so report that. (Mac, observed: this does NOT hold on the Mac client. While the callee's phone rings the Invite window stays open showing "Calling..." and Cancel, and the call UI itself is in the Zoom Workplace window. The bot does not cancel a ringing call on timeout and does not close the Invite window afterwards.)
9. Hold the UI lock only while acting. Waiting for the callee to answer is read-only.
10. A finished call must not block the next visitor. Mark the call record ended, or a 3-minute guard blocks the next escalation.
11. The Mac equivalent of a disconnected remote session is a **locked or sleeping screen**. Keep the Mac awake and unlocked (section 8).
12. (Mac, verified) Zoom refuses `AXPress` with error -25200 while it is not the frontmost app. `axctl activate --window RE` (sets `AXFrontmost` and raises the window) fixes it, even though it may print `zoom_frontmost:false`. `ui_backend` retries a refused press once after activating, except Call, which activates first and is pressed exactly once.

13. (Mac) Once the Call press has been attempted, the result is never "not placed". A refused press (-25200), a timed-out press (-25204, which can still take effect), or an unreadable screen afterwards becomes state `unknown`. The CLI prints `UNKNOWN, Call may have been placed` and the join log records `engineer_called=unknown`. Check Zoom and the phone before dialling again. A call that was answered but whose "Complete meeting invite" is still showing after the press (or whose press was refused) is `complete_failed`: the CLI prints `CALL PLACED, complete_failed: ...`, the call is recorded as placed and answered, and the screen text is saved to `logs/ui_debug.json`.
14. (Mac) Zoom ends a meeting after a period of inactivity or when the host is alone, and shows an idle-timeout warning first. Turn on Zoom Workplace -> Settings -> Meetings & webinars -> Advanced -> Advanced meeting -> "Do not automatically end meetings after inactivity". It may be locked by the admin. The other rules (55-minute inactivity timer, 40-minute alone rule) come from university IT pages and the Zoom community, not Zoom's official docs. If the pop-up still appears, capture its text (`axctl texts --window .`) so an auto-extend handler can be written.
15. (Mac, seen in a live test) When the bot is in a meeting and places the Zoom Phone call, Zoom shows "You have a meeting in progress. If you continue to make a call, your audio will be switched from the meeting to your phone call." with **Cancel** and **Continue**. Until Continue is pressed the callee is not added to the meeting. `ui_backend` now looks for this prompt after the Call press and again after the Complete press, in the Zoom Workplace window, titled windows and untitled windows. It presses Continue only when one window holds all three of the heading text "meeting in progress", a Cancel button and exactly one Continue button, and only when `find` returns exactly one match. It makes at most 3 Continue attempts per call (`MAX_CONTINUE`). Only a -25200 refusal (Zoom was in the background, so nothing happened) is retried: it activates the prompt's window, looks for exactly one Continue button again, and presses once more. A timeout (-25204) is not retried, because the press may already have worked. It never presses Cancel. Side effect: pressing Continue moves the bot's own Zoom audio from the meeting to the phone call. The spoken welcome does not depend on the bot's microphone (it is shared as computer sound, section 7b), but whether the share survives that audio switch is not known yet; the welcome starts as soon as the visitor is seen, normally before the call is placed. After Complete, the bot reports `completed` only when the screen has shown neither the Complete button nor the prompt's heading text (in any window, even if its buttons are not recognised) on clean reads spanning `SETTLE_GAP` (1.5 s), because the prompt can appear a moment after the button goes. If the heading is on screen but the buttons do not match, Continue is not pressed and the result detail says "not recognised". **Verified live once (2026-10-08)**: the run ended `DIALLED ... answered and added to the meeting [pressed Continue on Zoom's audio-switch prompt x1]`. A successful run writes no debug file, so the prompt's exact accessibility structure (untitled window, sheet or titled window; which field holds the button label) is still not recorded; we only know the handler found and pressed one Continue. One run is not a pattern, and the prompt's timing may vary. If a later run ends `complete_failed` or `timeout`, open `logs/ui_debug.json` (it lists every window, including untitled ones, with all their nodes) and tune the match.

## 6. Safety gates (do not weaken)

* `WARROOM_DRY_RUN=true` and `WARROOM_LIVE_CALLING=false` by default. Both must change for any real call.
* The gates fail closed: a blank, quoted-wrong or misspelt value (`ture`, `flase`) keeps the safe state. `WARROOM_TARGET_MODE` must be `test` or `roster` (anything else is an error), and `WARROOM_CALL_TIMEOUT` must be a number of at least 5.
* `dial`, `join` and `watch` print `gates: dry_run=... live_calling=... target_mode=...` to stderr. That line shows the values that actually won. A real environment variable beats `.env`, and for a duplicated key in `.env` the first line wins.
* Call guard: before a live call the dialer writes `logs/call_guard.json` (state `in_flight`, `unknown` or `link_opened`) and refuses a second live call for 180 seconds, or for the call timeout plus 120 seconds if that is longer (the guard file records its own `hold`). A call that ended cleanly (state `ended`) does not block the next visitor. A corrupt guard file also blocks. To clear a stuck guard once you have checked Zoom and the phone, delete `logs/call_guard.json`.
* In test mode `dial()` itself refuses any number except `WARROOM_TEST_NUMBER`, even if a caller passes another.
* `WARROOM_TARGET_MODE=test` discards roster numbers and dials only `WARROOM_TEST_NUMBER`. Roster mode also needs `WARROOM_ALLOW_ROSTER_CALLS`.
* Zoom-contact invites (`WARROOM_ZOOM_INVITE`) are off by default and sit behind the same gates as the call (dry run, `WARROOM_LIVE_CALLING`, the call guard). In test mode they go only to `WARROOM_TEST_ZOOM_EMAIL`, and `invite()` itself refuses any other address. The address is never printed or logged.
* Support is recognised by roster `zoom_email`, a roster phone number, or a number the bot dialled. Display names are used only if `WARROOM_TRUST_DISPLAY_NAMES` is enabled, because they are spoofable. (The watcher also treats whoever joins right after its own answered call as the engineer, by name, for the rest of that run.)
* The watcher places at most `WARROOM_MAX_CALLS_PER_HOUR` calls an hour (default 3), on top of the call guard.
* The webhook receiver fails closed, verifies the signature against the raw body, and has no test bypass.

## 7. Bring-up order on the Mac

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # resolves via Nexus
.venv/bin/python -m pytest -q
cp .env.example .env                            # keep WARROOM_DRY_RUN=true
```

1. Fix any test failures that are not UI-related first.
2. In `.env`, set `WARROOM_TEST_NUMBER` to a phone you control. Never use roster numbers while testing.
3. Grant **Accessibility** permission: System Settings -> Privacy & Security -> Accessibility, then add Terminal (or whichever app runs the bot).
4. Sign the Zoom Mac client in as the bot account and join the bridge.
5. Bring up the Mac `ui_backend`, in this order (run these in a terminal that has Accessibility permission, with the Zoom meeting open):
   1. `.venv/bin/python -m warroom.cli ui-probe`: read-only, lists the participants.
   2. `.venv/bin/python -m warroom.cli selftest`: rehearsal. Opens Invite, types a dummy number, reads it back, clears it, closes the window. It never presses Call.
   3. Real call-out to your test number. Pass the gates inline so `.env` stays closed:
      ```bash
      WARROOM_DRY_RUN=false WARROOM_LIVE_CALLING=true WARROOM_TARGET_MODE=test .venv/bin/python -m warroom.cli join "Test Visitor"
      ```
      Keep Zoom open, answer the phone, and leave the "You have a meeting in progress" dialog for the bot to handle (lesson 15). Check the `gates:` line before the call goes out. The answered-label, "Complete meeting invite" and Continue-prompt detection worked in both live Mac runs (2026-10-08) and have no other run behind them: if it ends `timeout` or `complete_failed`, `logs/ui_debug.json` holds the screen text for tuning (`WARROOM_ANSWER_PATTERN` overrides the answered-label regex; a blank, invalid or match-everything override is ignored). Exit code 0 means a dry run or a connected call, 1 means anything else including `unknown`, 2 means a config error.
6. Only then run the watcher (section 7a) with a test visitor.

## 7a. The join watcher (`watch`)

`join NAME` is a manual one-shot: it dials whether or not anyone joined. `watch` is the bot proper: it reads the Zoom participants list every `WARROOM_POLL_SECONDS` and acts when a new visitor appears.

```bash
.venv/bin/python -m warroom.cli watch          # safe: dry run, reads the list and prints what it would do
```

What it does, in order:

1. **Baseline.** The first good read is the starting point. Everyone already in the meeting is listed ("not greeted") and never called for, so restarting the watcher does not call for the whole room.
2. **Detect.** Each later read is compared with the last by display name, counting duplicates (two "Guest" rows are two people). A name has to be missing from two good reads in a row before it counts as having left, so one glitchy read cannot make someone look new when they come back.
3. **Greet.** The spoken welcome starts (`WARROOM_VOICE`; it is played into the meeting as shared computer sound, section 7b), then the watcher waits `WARROOM_GRACE_SECONDS` (default 10).
4. **Re-check.** It reads the list again. If the visitor has gone, nothing is dialled (the join log gets a `NOT CALLED: left during the grace period` row). If an engineer is already in the meeting it does not call either (`WARROOM_SKIP_IF_SUPPORT_PRESENT`, default true).
5. **Escalate.** It dials through the same gated dialer as `join` (call guard, test-mode number lock, dry run) and writes the same join-log row. Visitors who join in the same poll share one greeting and one call; the others get a `NOT CALLED: covered by the call placed for ...` row.
6. **Absorb the engineer.** After an answered (or uncertain) call it watches for about 10 seconds for the person who joined because of the call and remembers them as support, so they are not greeted as the next visitor and later visitors are not called for while they are there.

Who is never treated as a visitor: the bot's own `(me)` row, names in `WARROOM_IGNORE_NAMES` (comma separated, case-insensitive: note-takers, other bots), anyone shown by a phone number on the roster or the test number (a number without its country code also matches), and the engineer from step 6.

A read that fails (Zoom busy, panel closed, the bot's own row missing, the meeting on another desktop, a lock) is treated as a glitch, never as an empty room. The watcher never gives up on its own: it prints `read failed (N in a row, still watching)` at the 1st, 10th, 100th, 200th ... failure, and `reading the meeting again after N failed reads` when the window is back. Anyone who joined while it could not see is then greeted like any other new visitor. (Until 2026-10-09 it stopped after 20 failures, about a minute, which switched it off whenever the meeting window was out of sight for that long.) Only Ctrl-C stops it (exit 0; exit 1 if it landed while a call was being placed, in which case look at Zoom and the phone). Exit code 1 also covers no Accessibility permission and no meeting window at start-up.

**Switching it on and off.** From `~/warroom-mac`, in a terminal that has Accessibility permission, with the bot in the meeting:

| | Command |
|---|---|
| On (test mode, live calling, keeps the Mac awake) | `./watch.sh` |
| Off | Ctrl-C in the window it runs in, or `./watch.sh stop` from any other window |
| Is it on? | `./watch.sh status` |

`./watch.sh` fixes `WARROOM_DRY_RUN=false`, `WARROOM_LIVE_CALLING=true` and `WARROOM_TARGET_MODE=test`, so it can only ever dial `WARROOM_TEST_NUMBER`. It refuses to start a second copy. Whoever is already in the meeting when it starts is not greeted, so test with a visitor who joins after it is on.

| Setting | Default | Meaning |
|---|---|---|
| `WARROOM_POLL_SECONDS` | 3 | Seconds between reads (at least 1). |
| `WARROOM_GRACE_SECONDS` | 10 | Wait between the welcome and the re-check (0 or more). |
| `WARROOM_MAX_CALLS_PER_HOUR` | 3 | Calls the watcher may place per rolling hour (a whole number, at least 1). Dry runs do not count. |
| `WARROOM_SKIP_IF_SUPPORT_PRESENT` | true | Do not call when a recognised engineer is already in the meeting. |
| `WARROOM_TRUST_DISPLAY_NAMES` | false | Treat a participant whose display name matches a roster name as that engineer. Spoofable. |
| `WARROOM_IGNORE_NAMES` | empty | Names that are never visitors. |

A bad value for any of these is a config error (exit 2), not a silent default.

Live test, from a terminal that has Accessibility permission, with Zoom in the meeting:

```bash
WARROOM_DRY_RUN=false WARROOM_LIVE_CALLING=true WARROOM_TARGET_MODE=test .venv/bin/python -m warroom.cli watch
```

The visitor has to be someone other than the bot's account (a second device or account, or a phone dial-in); the bot cannot greet itself. Hang the test phone up (or remove the callee from the meeting) between tests, or the watcher will see an engineer and skip the call. The test number is the one `WARROOM_TEST_NUMBER` sets; nothing in test mode can dial anything else.

### Meeting window: full screen, windowed, minimised

The watcher reads and dials the same way in all three states (checked live on 2026-10-09, using `ui-probe` and `selftest`, which never press Call):

| Meeting state | Where Zoom puts the Participants panel and its Invite button |
|---|---|
| Windowed | Docked inside the "Zoom Meeting" window. |
| Full screen | In its own "Participants (N)" window. The meeting is its own macOS desktop (Space). |
| Minimised | Wherever it was when the window was minimised. Zoom keeps minimised windows readable, and a minimised Participants window also works. |

The watcher reads a detached Participants panel even when the main meeting window is hidden. It requires a unique Participants list containing the bot's own row; an unreadable list never counts as an empty room. Zoom can hide all relevant windows on another macOS desktop. In that case the watcher periodically brings Zoom forward, with at least 30 seconds between recovery attempts, and resumes when the list is readable. This may switch desktops. Accessible lists are read without activation. Version 20261012.7 adds this recovery and recognizes Zoom's duration-suffixed meeting titles; its behavior with the target Mac's real Zoom windows still needs verification.

Full screen and the call controls: the answer timer and "Complete meeting invite" live in the "Zoom Workplace" window, which is on a different desktop from a full-screen meeting, so it was unclear whether the watcher could see the answer. One real watcher-placed call in full screen (2026-10-09) ended `answered and added to the meeting`, so it works at least in that setup. If a call ever ends `timeout` with a detail saying the Workplace window is not visible, `logs/ui_debug.json` lists the windows it could see; the phone is then answered but not added to the meeting. One run is not a pattern: windowed or minimised remains the better-proven state.

## 7b. The spoken welcome: shared computer sound

The Windows bot plays its welcome into the meeting as Zoom shared content, not through a microphone, so nobody has to unmute. The Mac port does the same (`WARROOM_VOICE_ROUTE=share`, the default):

1. `say` renders the message to a temporary file (the text goes in on stdin).
2. The bot starts an audio-only share: toolbar **Share** -> "Share screen window" -> **Other Tab** -> **Computer audio, Share audio** -> **Share - Computer audio**. It never presses a "Share - Desktop ..." button, so no screen is ever shared.
3. It waits until Zoom shows the share (the **My computer sound** tab and the text "Computer audio is being shared in Mono"), waits one second, and plays the file with `afplay`.
4. It waits one second, then stops the share. Zoom's close button for it (`close My computer sound`) only exists while that tab is selected, so the bot clicks the tab first (a real mouse click, `axctl click`, which puts the pointer back) and then presses the close button. It then checks the share is really gone.

The greeting runs on its own thread, in parallel with the call: the dial is issued without waiting for the welcome, and the CLI waits for the welcome only afterwards, so the join log can say how it went. Both drive Zoom, but `ui_backend` lets only one UI sequence act at a time (the call releases that lock while it waits for the phone to be answered, so the share's steps slot in). There is one known hazard, seen live on 2026-10-09: while the bot is **Presenting**, the "Zoom Meeting" window drops out of Accessibility as soon as the dial brings Zoom Workplace forward, so the share could not be stopped and the watcher went blind. So the share's start and stop first check that the meeting window is visible, and if it is not they bring Zoom forward (`open -a zoom.us`, like clicking its Dock icon) and wait up to `SURFACE_WAIT` (8 s) for it to come back. The share requires the main window; participant polling instead uses detached lists when available and its own throttled visibility recovery when needed. Side effect: if the meeting is full screen on another desktop, bringing Zoom forward switches you to that desktop. A `local` voice (`WARROOM_VOICE_ROUTE=local`) never touches Zoom. If anything fails there is no fallback to the local speakers: the join log's `welcome_voice` says `FAILED: <why>` and the call goes ahead. If the share cannot be stopped, the bot prints `WELCOME SHARE STILL RUNNING` (also at exit, including Ctrl-C): click the x on the **My computer sound** tab in Zoom, or run `.venv/bin/python -c "from warroom import ui_backend as u; u.stop_audio_share()"` (that now brings the meeting window forward by itself).

Settings: `WARROOM_VOICE` (on/off), `WARROOM_VOICE_ROUTE` (`share` or `local`; `local` plays on this Mac's speakers only, as before; anything else is a config error), `WARROOM_VOICE_NAME`, `WARROOM_VOICE_MESSAGE`, `WARROOM_VOICE_IN_DRY_RUN`.

Try it by hand with someone in the meeting to listen. It places no call and writes no log, and ignores dry-run and `WARROOM_VOICE`:

```bash
.venv/bin/python -m warroom.cli voice-test
```

What has and has not been proven (2026-10-09): the share steps and the Zoom labels above were mapped live, and a test joiner confirmed hearing the greeting played as shared computer sound, with the bot's microphone muted and no audio connected. Not yet proven live: the full watcher sequence with the welcome and the call running in parallel (including the share's stop bringing the meeting window back after the dial hid it), and that the stop works from an unselected tab. Because a share changes the meeting for everybody in it, run `voice-test` only when you are ready to click the x on the tab yourself.

## 7c. Zoom Contacts plus a phone call (optional, off by default)

The bot can invite the on-duty engineer through **Invite → Contacts** by their displayed contact name and also call their roster phone number for the same visitor. The invitation appears in the engineer's Zoom app; the bot does not use Zoom's Email tab or send an email.

In War Room Bot, stop the watcher, choose **Calling options → Go**, select **Zoom Contacts + phone**, and save. Roster mode searches Contacts using the selected engineer's roster `name`; enter the name as shown in Zoom Contacts. The optional **Test Zoom contact name** applies only to test mode. Leave it blank for phone-only tests, or enter a separate contact you intend to invite. Each **Start: test number** asks for a number in a blank field; a saved number is never reused by that app action. Saving these options does not start a watcher, invite anybody, or place a call. Selecting **Phone only** disables Contacts invitations again.

For source installs, the equivalent settings are:

```dotenv
WARROOM_ZOOM_INVITE=true
WARROOM_ZOOM_CONTACT_LOOKUP=name
WARROOM_TEST_ZOOM_CONTACT=
```

Stop the watcher before editing these settings. Existing roster and live-calling gates still apply. Name lookup ignores the roster's `zoom_email` and `WARROOM_TEST_ZOOM_EMAIL`, including when the test contact name is blank. Older configurations can retain `WARROOM_ZOOM_CONTACT_LOOKUP=email`; saving through **Calling options** switches to name lookup atomically with the other options.

For each eligible new visitor, the bot sends the Contacts invitation first, then starts the phone call without waiting for the Zoom invitation to be accepted. The UI steps run in sequence because they share Zoom's Invite dialog. A failed Contacts lookup or invitation is reported separately and the phone call still proceeds. Interrupting the invitation stops the remaining call sequence. Dry runs send neither invitation nor phone call.

The Contacts lookup types the name into "Add contacts", verifies that the filter accepted it, and requires exactly one matching displayed name, ignoring case and surrounding spaces. It also checks that the selected Accessibility element is unique and that Invite becomes enabled before pressing Invite once. Missing or duplicate exact names, an unreadable filter, and a disabled button produce a reported failure without inviting a guessed contact. The person must already be in the bot account's Zoom Contacts. Afterwards the bot restores the Invite dialog to Zoom Phone for the phone route.

The watcher correlates one newly arriving participant with the contact row actually selected for an invitation, so that arrival does not immediately trigger another escalation. This is a temporary display-name association, not account verification: it expires if nobody arrives within three minutes after escalation finishes, and is removed when the person leaves or duplicate names appear. A confirmed invitation can mark that arrival as support; an uncertain invitation only suppresses escalation for that arrival, while other visitors can still trigger a call.

Before using real roster contacts, choose **Dry run: roster** and review the selected engineer and both destinations. For a live test, save your intended test contact name, then choose **Start: test number**, enter your own phone in its blank field, and review the confirmation. **Recent activity** and `logs/join_log.csv` record Contacts and phone outcomes separately. Name lookup and the combined sequence are covered by simulated tests; a live invitation and phone call still need verification with the target Mac's Zoom account and Contacts list.

## 7d. War Room Bot.app

A native Cocoa controller plus the same runtime files as the ZIP, packed in a universal DMG by `tools/build_app.sh`. Quickstart: `README.md`. Versions through 20261012.5 used the retained AppleScript source; the native app supersedes that controller.

* Actions call `app/wrb.sh` with an argument array through a direct `Foundation.Process` running `/bin/bash`. The native host silently checks its own AX permission, and its explicit Request Accessibility action requests the system alert. Open Settings is a separate action. The signed helper is inside `Contents/MacOS/axctl`; `WARROOM_AXCTL` selects it for native-launched controllers and Python workers. Terminal defaults to the data-folder helper.
* `WARROOM_HOME` (default `~/WarRoomBot`) is the install folder. Set-up copies the app's files there with `ditto --noqtn`, then runs `install.sh` with tests enabled. Payload copying preserves `.env`, `roster.xlsx`, `logs/`, `.venv` and `tools/axctl`; the installer updates dependencies and rebuilds the helper. `.env` and `roster.xlsx` are set to owner-only.
* **Start: test number** asks for a number on every start, previews that explicit entry, and passes it only to the new worker through `wrb.sh start NUMBER` and a process environment override for `watch.sh start`. It never writes the entry to `.env`. Cancel and blank/invalid entries cannot start a watcher. Source-only `./watch.sh start` continues to use explicitly configured `.env` settings. **Clear saved test number** removes an older saved value while preserving other settings; normal call logs can still record numbers used. **Preview on-duty roster**, **Dry run: roster** and **Start: roster** are explicit separate actions; live roster start verifies a real target and asks for confirmation. Source commands `watch.sh roster-preview`, `roster-dry` and `roster` provide the same modes. The native host sets `WARROOM_APP_FOREGROUND=1` so the wrapper execs its worker without `nohup`/`disown`; the worker remains the app's direct child and writes `logs/watcher.log`. Closing the window hides the app; Quit offers Stop and quit or Hide and keep watching. Terminal can be closed.
* Exit codes of `wrb.sh`: 0 ok; 10 developer tools requested; 11 Nexus unreachable; 13 watcher running or status unknown (update refused); 20 not set up; 21 another watcher is running; 22 no test number; 23 Accessibility not allowed; 24 watcher did not stay up; 25 watcher still stopping after 20 seconds; 26 invalid or missing roster target; 2 usage.
* The app is ad-hoc signed by default and is not notarized. Local builds can use an IT-supplied keychain signing identity and bundle identifier. Existing declared identifiers are preserved automatically; otherwise the default is `com.equinix.warroombot`. An identifier alone does not preserve grants for changed ad-hoc code. Verify native permission, bundled-helper permission, Check and Dry run on the target Mac. Keep only the installed Applications copy open; eject older disk images to avoid confusing equal display names.
* Tests: `tests/test_wrb.py` (fake `pgrep` and `axctl`, throwaway install folder). The dialogs themselves and the Accessibility grant can only be tried by a person.

## 8. Running it on a Mac

Keep the machine awake and unlocked. Run the bot under `caffeinate`:

```bash
caffeinate -dimsu .venv/bin/python -m warroom.cli watch
```

Minimal double-clickable launcher, saved as `start.command` and made executable with `chmod +x start.command`:

```bash
#!/bin/bash
cd "$(dirname "$0")"
exec caffeinate -dimsu .venv/bin/python -m warroom.cli watch
```

### Does it work with the screen locked?

Not proven, and not to be relied on. The bot drives Zoom by pressing buttons through macOS Accessibility, which needs a live, unlocked desktop session; a locked screen (or a sleeping Mac or a closed lid, which ends everything) should be expected to make the reads fail ("no Zoom meeting window") and the watcher to stop after 20 failed reads. A running meeting can survive a lock, but the bot cannot work the Zoom windows through it. So: do not lock the screen while the watcher runs. Use `caffeinate` (above) to stop idle sleep, and set the screen saver / lock-after-sleep delay to Never for the watcher account, or run the watcher on a dedicated Mac that stays unlocked. A locked screen shows as the key `CGSSessionScreenIsLocked` in `ioreg -n Root -d1`. The watcher does not check for it yet.

A laptop that is also a daily machine sleeps, locks and logs out, so it is a poor production host. A dedicated always-on Mac (a spare Mac mini would fit) with Zoom signed in under the bot account suits production. Set Energy to prevent sleep, disable the screen-lock password timeout for that account, and use `launchd` for auto-start.

If Zoom app credentials can be obtained, a webhook + REST backend could run without a desktop (not built here). It cannot post a chat greeting.

## 9. Review status and known gaps

An independent review of the first dialer (42 findings confirmed or plausible, 9 refuted) drove the fail-closed config, the `unknown` state, the call guard, the number re-read after bringing Zoom forward, and print-before-log in `join`. Those fixes are covered by `pytest` (225 tests, none of which can reach the real Zoom: `tests/conftest.py` replaces the accessibility helper with one that fails loudly). The fixes themselves have not been independently re-reviewed. The audio-switch (Continue) handler added after the first live tests is covered by 12 prompt tests against a fake that mimics `axctl` window scoping, and a mutation check (handler disabled) failed 9 of them; it was written after the review above, and its first two live runs (2026-10-08) succeeded. A second, partial review of that handler (3 of its 4 lenses finished; the tests lens did not, and it was stopped early at the user's request) confirmed 14 findings. All 14 were fixed afterwards, without a further independent review: the audio-switch retry now only follows a -25200 refusal and looks again before pressing; completion also needs the prompt's heading text gone and the screen clean for 1.5 s; the dial guard outlasts long timeouts, a failed guard or debug-file write after the call no longer hides the result, Ctrl-C during a call prints `UNKNOWN` instead of a traceback, an `uncertain` result is logged as `unknown`, and the misleading "Invite window is still open" note was removed. Each fix has a test, and 15 hand-made regressions of them were each caught by the suite.

Left as designed or not yet possible:

* The spoken welcome says an engineer is being called whatever the dial outcome.
* No test can show that Zoom dials the text set through `AXValue`. Only a live call proves it.
* The "Complete meeting invite" press and the Continue prompt handler (lesson 15) succeeded in two live runs (2026-10-08), and the prompt's accessibility structure was not captured. The Invite window stays open after Call and after a timeout, and a ringing call is not cancelled on timeout.
* `welcome_voice` in the join log records `yes` when the share was started, the sound played and the share stopped, or `FAILED: <why>`. It cannot show that anyone heard it.
* The spoken welcome plays whether or not the call was placed, because voice and dial start together.
* `find` and `press` are separate `axctl` runs, so between checking for the one Continue button and pressing it the screen could change. The check confirms exactly one match, in the expected window, right before the press; it cannot close that gap completely.
* Not built yet: the chat panel (so no chat greeting). Zoom-contact invites (section 7c) are built and tested against a fake but have not been run live.
* The welcome is played as a Zoom computer-audio share (section 7b). A joiner heard it live (2026-10-09). Not yet proven live: that the share stops by itself when the welcome finishes before the dial, and how it behaves alongside the Continue audio-switch prompt during a real call. While the bot is Presenting the "Zoom Meeting" window is hidden from Accessibility once Zoom Workplace is in front, which is why the call waits for the welcome.
* Zoom 7.2.1 writes the bot's own participant row as `Name (Host, me, Participant ID:355195)`. The parser knows the `Participant ID:NNN` tag (`ID_TAG` in `ui_backend.py`); without it the own row was not found and every read failed.
* `welcome_voice` can say `FAILED: share left running` although the sound did play and was heard: only the stop failed.
* The join watcher has read a real participant list and detected a real joiner live (2026-10-09, full screen); its dial step has so far only been checked live as a rehearsal (no Call). Unknown until a live run: how the engineer appears in the Mac participants list (name or phone number), and whether `participants` stays reliable over a long poll. It has had no independent review; hand-made regressions of its main rules (debounce, baseline, re-check, support check, ignore list, call cap, Ctrl-C handling) were each caught by its tests.
* Visitors are told apart by display name only (the Mac list exposes no participant id), so if one person leaves and a different person with the same name joins before the watcher notices the gap, it sees no change and does not greet them; a person who renames themselves looks like a new visitor.
* Zoom may end an idle meeting. In Zoom Workplace, Settings -> Meetings & webinars -> Advanced -> Advanced meeting, switch on "Do not automatically end meetings after inactivity" if you can (an admin may lock it); otherwise the meeting ends and the watcher keeps printing `read failed ... still watching` until you stop it or start a new meeting. (Taken from Zoom's support pages, not tried on this Mac: the label reads "Do not ...", so the box should be ticked for Zoom to leave the meeting alone.) The watcher does not tell a new meeting from the old one: people already in a new meeting when the window comes back are greeted, and called for, as new visitors. Restart it (`./watch.sh stop`, then `./watch.sh`) after a meeting ends.
* When the engineer's call is answered, Zoom moves the bot's own meeting audio to the phone call (the Continue prompt). It is not known whether this also affects a computer-audio share that is running at that moment.
* The fake Zoom in the tests ignores selectors, so a wrong selector would not fail a test.
