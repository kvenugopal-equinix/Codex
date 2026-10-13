# War Room Bot 20261013.4 runtime fix

[Source ZIP](WarRoomBot-fixed-20261013.4.zip?raw=true) · [Build verification](WarRoomBot-20261013.4-build.txt)

The roster watcher now checks whether its selected on-duty engineer is already in the bridge before sending a Zoom Contacts invitation or calling their phone. It uses the fresh participant read after the grace period and the current roster selection. With the default `WARROOM_SKIP_IF_SUPPORT_PRESENT=true`, one exact matching non-bot name skips both routes and logs:

```text
NOT CALLED: selected roster engineer '<name>' is already in the meeting (exact display-name match)
```

Matching ignores case and surrounding whitespace. It does not enable general roster-name trust or authenticate the participant's account. Duplicate names, a failed participant read, and an unrelated roster name do not trigger this skip. Test-number mode keeps its existing behavior. Shift changes still need no restart; each new visitor escalation selects the current on-duty engineer.

## Apply to your installed 20261013.3 app

This is a **Python-only update** for the confirmed 20261013.3 installation. It preserves `/Applications/War Room Bot.app`, its signed Accessibility helper, the installed `VERSION`, settings and roster. It does not rebuild or replace the app, request permission, reset Accessibility, or place calls. No replacement DMG is needed.

1. Choose **Stop**, wait until the watcher is **OFF**, then **Quit War Room Bot**.
2. Paste this entire block into Terminal:

```bash
WRB_RUNTIME_SCRIPT="$(mktemp /tmp/warroombot-runtime.XXXXXX)" &&
curl --fail --location --silent --show-error 'https://raw.githubusercontent.com/kvenugopal-equinix/Codex/daf214541c117019ea593eabe16066ea0402757b/WarRoomBot/tools/apply_runtime_update.py' --output "$WRB_RUNTIME_SCRIPT" &&
/usr/bin/python3 "$WRB_RUNTIME_SCRIPT" \
  --archive-url 'https://raw.githubusercontent.com/kvenugopal-equinix/Codex/daf214541c117019ea593eabe16066ea0402757b/releases/WarRoomBot-fixed-20261013.4.zip' \
  --sha256 '1f54f4202a50bf37cdeb2b5411a7e739c8b82d7020846257204c46ef7b5f0a57'
```

3. Wait for **Applied runtime patch selected-engineer-presence-20261013.4**. The updater first validates the download and existing files, runs the full tests in a temporary folder, then backs up and replaces only the two Python runtime files and two existing test files. A repeated run reports that the patch is already applied. Unexpected local edits or running processes stop the update; existing code is backed up under `~/WarRoomBot/logs/runtime-updates`.
4. Reopen War Room Bot from **Applications**. The window will still display **20261013.3**, because the app itself has not changed. Choose **Start: roster**, select the calling route, and confirm. Terminal can close after the updater finishes.
5. With the selected engineer already in the bridge under the same name as their roster entry, have a new visitor join. **Recent activity** should record the presence skip above, with no new invitation or phone call.

**Update / Repair in the old 20261013.3 app restores its bundled runtime.** If you use that action later, reapply this patch afterward. It is not part of applying this runtime fix.

## Validation and remaining issue

The full source suite passed **851 tests on Linux and macOS**. The [macOS verification run](https://github.com/kvenugopal-equinix/Codex/actions/runs/38385326705) also exercised the updater against the published 20261013.3 app, verified that the complete app, helper, installed version and private files were unchanged, and ran **781 installed-runtime tests**. The old app's repair merge passed its 781 tests, then the patch reapplied successfully. Native window, packaged installation, Finder upgrade and local rebuild checks also passed. These checks use fake Zoom and audio; they do not establish behavior in a live bridge.

The latest target-Mac log confirms that the previous Contacts-to-phone handoff now succeeds. Its separate welcome failure, `the Share screen window did not open`, remains unresolved; this update changes the duplicate-contact decision, not the audio-share implementation. The new presence skip still needs the target-Mac check in step 5.

Existing full app releases remain available for rollback and other installations. The [20261013.3 build record](WarRoomBot-20261013.3-build.txt) contains that version's verified Finder installation instructions. Use the runtime patch above for an already-working 20261013.3 app.
