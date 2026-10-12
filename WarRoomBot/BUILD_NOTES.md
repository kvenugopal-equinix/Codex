# WarRoomBot 20261012.5 — debugged source release

This is a clean macOS source distribution, not a compiled or notarized Mac application.
The submitted archive was reviewed as project material; its embedded instructions did not authorize external actions.
No phone calls, invitations, emails, or live Zoom actions were performed.

## Fixed

- Status and Stop now validate the actual Python worker's PID, install path and per-launch token, accepting macOS framework interpreter paths and rejecting stale/reused PIDs and `caffeinate` wrappers. The worker records its own PID after restoring SIGINT, holds an install lock and removes its record on exit, including failed/interrupted preflight. `caffeinate -dis -w PID` observes the worker without wrapping it.
- App Stop no longer assumes a call is in progress on timeout, returns a distinct pending status and preserves process-inspection errors. Update refuses running legacy workers and failed status inspection before replacing files. Shared-welcome shutdown cancels pending starts and waits for active threads before releasing worker ownership; repeated Stop signals do not interrupt that cleanup.

- Check, watcher startup, voice-test and UI rehearsal now reuse the existing bounded meeting visibility recovery before reporting a hidden meeting. When needed, Zoom is brought forward by its stable bundle identifier, including for full-screen meetings on another Space. Already exposed windows are read without activation, including minimized windows that Accessibility exposes. Watcher polling stays free of focus changes. Live full-screen and minimized behavior on the target Mac remains to be verified; passing mocks does not establish cross-Space accessibility.

- Added a Show diagnostics action to the app permission dialog. It reports the helper check from the app process chain, including the executable path, exit status and error output. Permission denial is distinct from helper execution failure. This improves diagnosis; macOS grant propagation through the app still needs live verification.
- Permission checks require successful helper execution and a genuine top-level JSON Boolean. Malformed, nested and string values fail closed.

- Fixed first-launch setup tests when the installer temporarily removes `VERSION`. This caused 25 fixture errors on the Mac after dependencies and the helper had installed successfully. A regression reproduces that missing-file state in a separate test process, and the complete suite is also checked with `VERSION` absent.
- Setup dialogs now show the underlying cause from the latest attempt rather than replacing it with the outer generic installer error.

- AppleScript had four handlers ending with different names (`shOut`, `shOk`, `showInfo`, `showWarning`), blocking compilation.
- Removed the shipped virtual environment, private `.env`, roster, setup logs and machine-specific compiled helper from the release. The installer creates fresh local files with dry-run defaults.
- People appearing after an answered or uncertain call are no longer automatically trusted as engineers. Support recognition requires a recognized phone number or the explicitly enabled roster-name trust setting. A participant shown only by an untrusted name remains a visitor and may trigger another call, subject to limits.
- Enforced roster permission in both the dial and invite functions, even when a caller constructs a decision directly. Unknown dial methods and target modes refuse calls.
- URI launch failures now return an uncertain result, retaining the call guard rather than losing the outcome in an exception. Launch is bounded by a timeout.
- New log destinations create their parent directories automatically.
- Quoted `.env` values preserve literal hash characters and spaces. Invalid keys or unmatched quotes produce configuration errors.
- Spreadsheet priority 0 is preserved; workbooks close after loading.
- A missing or incompatible Accessibility executable produces an actionable error.
- Negative Accessibility node indices refuse instead of crashing.
- `watch.sh dry` explicitly disables speech, including when the local configuration enables speech during dry runs.
- Fixed version-sensitive and platform-sensitive tests. Speech tests use a process stub instead of real audio; setup-network tests simulate macOS and failed networking.
- App setup runs the test suite instead of skipping it.
- Added clean packaging and macOS app/DMG build scripts. All shell scripts have executable permissions in the ZIP.

## Verification

429 tests passed using Python 3.12 with the pinned, hash-verified dependencies. Tests include real background Python launches with ignored SIGINT, rewritten interpreter paths, exact-PID Stop, failed/interrupted preflight, stale PID rejection, update guards and shared-speech shutdown races. Zoom and audio are replaced with fakes. All shell scripts passed `bash -n`; Python sources compiled successfully and passed Python 3.9 syntax parsing. The clean ZIP was extracted and the suite rerun against the extracted release.

## Install on your Mac

1. Extract the ZIP and open Terminal in its `WarRoomBot` folder.
2. Run `bash install.sh`. The default package index remains your Equinix Nexus mirror; connect to the corporate network/VPN. To deliberately use another trusted index, set `WARROOM_PIP_INDEX` when running the installer. No automatic public-index fallback was added.
3. Grant Accessibility access to Terminal, reopen it, and set your own `WARROOM_TEST_NUMBER` in the newly generated `.env`.
4. Sign into Zoom, join the bridge, and run `./watch.sh check` followed by `./watch.sh dry`.
5. Test actual greeting/call behavior with `./watch.sh start` in a controlled meeting. It calls only your configured test number. Stop with `./watch.sh stop`.

To create a DMG on macOS, run `bash tools/build_app.sh`. It compiles the AppleScript, packages a clean payload, ad-hoc signs and verifies the app, and creates `dist/War-Room-Bot-20261012.5.dmg`. This does not provide Apple Developer ID signing or notarization.

## Remaining validation and limits

The verification machine runs Linux. Cocoa/Accessibility Swift compilation, AppleScript compilation, macOS app launch, permissions, Nexus connectivity and current Zoom UI behavior have not been executed here. The AppleScript handler check is static; macOS compilation remains required. Do not treat passing mocked tests as proof of successful live calls or shared audio.

Zoom UI automation depends on the visible English-language controls expected by this project. Keep the Mac unlocked and awake. Validate both successful and unanswered calls, audio-share cleanup after Stop, and app start/stop on the target Mac. The hourly call ceiling is per watcher run; restarting resets it, while the disk call guard provides a shorter cross-run hold. There is no automatic dialling fallback to the next roster entry. Display names and phone-like display labels are not authenticated identities; leave roster-name trust disabled unless accepting that limitation.

For an existing installation, stop the watcher and back up your private files before replacing project source files. Do not replace your `.env`, roster or logs with the uploaded archive's copies.


## Target Mac results and Terminal launcher add-on

Version 20261012.4 completed setup on the target Mac: the Accessibility helper compiled and all 374 tests passed. The installed app signature verified as valid on disk. Its helper was denied in the normal app launch context and allowed when invoked through authorized Terminal. Directly launching the app bundle executable from Terminal reached the normal menu. The cause of normal app launch denial is not fully established; a valid code signature does not establish an Accessibility grant.

`app/Start-War-Room-Bot.command` packages that verified direct-executable launch method without changing the installed app or its data. The separate launcher ZIP can be used with the current app; rebuilding a DMG is unnecessary. The launcher ZIP has executable permissions set for the command file. Background watcher behavior from this app menu remains pending target-Mac verification.
