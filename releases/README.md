# War Room Bot release files

The [20261015.1 source candidate](WarRoomBot-20261015.1-source.zip?raw=true) contains the activity workbook runtime update, a separate Finder location chooser for the installed 20261013.3 app, and the complete app source. Put the [Terminal launcher](Update-War-Room-Bot-20261015.1.command) beside the ZIP and follow [its status record](WarRoomBot-20261015.1-status.txt). The native 20261015.1 DMG and app ZIP must be built and verified on macOS before they are shared as full app files.

## 20261013.4 runtime fix

[Source ZIP](WarRoomBot-fixed-20261013.4.zip?raw=true) · [Build verification](WarRoomBot-20261013.4-build.txt)

The roster watcher now checks whether its selected on-duty engineer is already in the bridge before sending a Zoom Contacts invitation or calling their phone. It uses the fresh participant read after the grace period and the current roster selection. With the default `WARROOM_SKIP_IF_SUPPORT_PRESENT=true`, one exact matching non-bot name skips both routes and logs:

```text
NOT CALLED: selected roster engineer '<name>' is already in the meeting (exact display-name match)
```

Matching ignores case and surrounding whitespace. It does not enable general roster-name trust or authenticate the participant's account. Duplicate names, a failed participant read, and an unrelated roster name do not trigger this skip. Test-number mode keeps its existing behavior. Shift changes still need no restart; each new visitor escalation selects the current on-duty engineer.

## Apply to your installed 20261013.3 app

This is a **Python-only update** for the confirmed 20261013.3 installation. It preserves `/Applications/War Room Bot.app`, its signed Accessibility helper, the installed `VERSION`, settings and roster. It does not rebuild or replace the app, request permission, reset Accessibility, or place calls. No replacement DMG is needed.

1. Choose **Stop**, wait until the watcher is **OFF**, then **Quit War Room Bot**.
2. Use the code block Copy button and paste this single command into Terminal (it may wrap visually). If cancelling a previous attempt, press Ctrl+C once and wait for the normal prompt first:

```bash
WRB_RUNTIME_SCRIPT="$(mktemp /tmp/warroombot-runtime.XXXXXX)" && curl --fail --location --show-error --progress-bar --connect-timeout 10 --max-time 60 'https://raw.githubusercontent.com/kvenugopal-equinix/Codex/c5612f9ab880ff662abc60d2ed8c57c0998d1201/WarRoomBot/tools/apply_runtime_update.py' --output "$WRB_RUNTIME_SCRIPT" && /usr/bin/python3 -u "$WRB_RUNTIME_SCRIPT" --archive-url 'https://raw.githubusercontent.com/kvenugopal-equinix/Codex/daf214541c117019ea593eabe16066ea0402757b/releases/WarRoomBot-fixed-20261013.4.zip' --sha256 '1f54f4202a50bf37cdeb2b5411a7e739c8b82d7020846257204c46ef7b5f0a57'
```

3. The updater displays stages 1/6 through 6/6. At stage 4, tests can run for up to five minutes, with progress and the latest test output printed every 15 seconds. If they time out, the updater prints the last test output and leaves installed files unchanged. The initial script download stops after 60 seconds if it cannot finish. Wait for **Applied runtime patch selected-engineer-presence-20261013.4**. The updater first validates the download and existing files, runs the full tests in a temporary folder, then backs up and replaces only the two Python runtime files and two existing test files. A repeated run reports that the patch is already applied. Unexpected local edits or running processes stop the update; existing code is backed up under `~/WarRoomBot/logs/runtime-updates`.
4. Reopen War Room Bot from **Applications**. The window will still display **20261013.3**, because the app itself has not changed. Choose **Start: roster**, select the calling route, and confirm. Terminal can close after the updater finishes.
5. With the selected engineer already in the bridge under the same name as their roster entry, have a new visitor join. **Recent activity** should record the presence skip above, with no new invitation or phone call.

**Update / Repair in the old 20261013.3 app restores its bundled runtime.** If you use that action later, reapply this patch afterward. It is not part of applying this runtime fix.

## Validation and remaining issue

The full source suite passed **851 tests on Linux and macOS**. The [macOS verification run](https://github.com/kvenugopal-equinix/Codex/actions/runs/38385326705) also exercised the updater against the published 20261013.3 app, verified that the complete app, helper, installed version and private files were unchanged, and ran **781 installed-runtime tests**. The old app's repair merge passed its 781 tests, then the patch reapplied successfully. Native window, packaged installation, Finder upgrade and local rebuild checks also passed. These checks use fake Zoom and audio; they do not establish behavior in a live bridge.

The latest target-Mac log confirms that the previous Contacts-to-phone handoff now succeeds. Its separate welcome failure, `the Share screen window did not open`, remains unresolved; this update changes the duplicate-contact decision, not the audio-share implementation. The new presence skip still needs the target-Mac check in step 5.

Existing full app releases remain available for rollback and other installations. The [20261013.3 build record](WarRoomBot-20261013.3-build.txt) contains that version's verified Finder installation instructions. Use the runtime patch above for an already-working 20261013.3 app.

The progress-reporting updater separately passed 50 regression tests and the local patch / old Repair / reapply integration cycle. The five-minute deadline remains fixed across progress messages; interruption stops only its own test process group. The original source ZIP and runtime patch bytes are unchanged.
