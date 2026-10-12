# WarRoomBot 20261012.6 — standalone Mac controller

Source ZIPs contain clean source. The macOS workflow builds a universal DMG; signing defaults to ad-hoc integrity signing, with an optional local IT signing identity. This does not provide Developer ID notarization.
The submitted archive was reviewed as project material; its embedded instructions did not authorize external actions.
No phone calls, invitations, emails, or live Zoom actions were performed.

## Fixed

- Replaced the long-running AppleScript menu with a native Cocoa controller. The native host silently checks its own Accessibility permission and verifies the actual bundled helper before starting. Requesting the macOS permission alert and opening System Settings are separate user actions; there is no repeating permission-dialog loop.
- The helper is compiled into `War Room Bot.app/Contents/MacOS/axctl`, signed before the enclosing app and selected explicitly by the host. Terminal's default data-folder helper remains separate. Helper results require a real top-level Boolean and successful exit status for success.
- The native app directly owns the watcher process instead of detaching through `nohup`/`disown`. Closing the window hides the running app; Stop and quit waits for actual worker completion. A native status item restores the window. This removes the Terminal launcher dependency, while actual macOS permission attribution remains to be verified.
- Added explicit roster preview, rehearsal and live-start controls. Live roster start verifies a real on-duty target and asks for confirmation; test-number Start remains separate. The roster is re-read for each escalation, respects shifts/timezones, and chooses the lowest numeric priority without automatic fallback.
- Setup progress is inline in the native window and is cleared after completion. The legacy AppleScript source now resets all four progress properties instead of leaving the previous test-phase description.
- The native bundle declares `com.equinix.warroombot` by default. Local builds preserve an existing declared identifier or accept an explicit IT identifier. The user's installed AppleScript build reported no `CFBundleIdentifier`; the new identifier is not evidence that the missing field was the sole cause of its denied helper check. App name, Applications path and private data folder stay the same.

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

483 runtime tests passed using Python 3.12 with the pinned, hash-verified dependencies. Added tests cover bundled helper paths, forged permission results, roster gates/preview, foreground app-child PID/parent identity and graceful shutdown. Zoom and audio are replaced with fakes. macOS CI compiles both architectures, signs/verifies the bundle, runs a bundle check and verifies the DMG. It now also opens the actual native window and checks that its main event loop responds and its read-only installation check completes, both by executing the binary and through LaunchServices. The UI checks use separate temporary data paths and never start setup, request Accessibility permission, access Zoom or start a watcher.

The startup investigation reproduced neither a layout exception nor a window-launch failure on the macOS 15 and macOS 26 runners. On macOS 26, direct execution and LaunchServices both reported a visible main window and completed startup in about one second ([CI run](https://github.com/kvenugopal-equinix/Codex/actions/runs/38239746637)). The launch-check instrumentation is newer than the published 20261012.6 DMG; these checks do not establish that the installed download can execute on the target Mac.

The target Mac reported no window and a hanging `--smoke-test`, which runs before creating `NSApplication` or querying Accessibility. Its installed signature verified, while `spctl --assess` rejected the ad-hoc build. That assessment is expected for unnotarized ad-hoc code and does not, by itself, prove that the user's Open Anyway approval failed. A process sample showed only `_dyld_start` and no binary-image description; system-log access was denied. Targeted quarantine isolation and further early-startup checks are needed before claiming a cause or a verified target-Mac fix. No Accessibility reset or global Gatekeeper change was performed.

Further target-Mac checks showed that removing the app's quarantine attributes did not resolve the hang. The bundled `Contents/MacOS/axctl trusted` also hung, while the locally compiled `~/WarRoomBot/tools/axctl trusted` returned `{"ok":true}`. This narrows the comparison to downloaded versus locally built executables, without proving an exact loader or execution-policy cause. `tools/rebuild_installed_app.sh` now rebuilds the existing app's clean payload with the local Swift tools in a separate private temporary folder, preserves its name/identifier, applies bounded copy/build deadlines, and opens the resulting DMG for manual installation. It never replaces the installed app or private data automatically. Owned-process-group cancellation was checked against an unrelated process, and the complete rebuild from a read-only mounted app passed on macOS 26 ([CI run](https://github.com/kvenugopal-equinix/Codex/actions/runs/38243337104)). The target-Mac rebuild result is still required.

## Install on your Mac

1. Extract the ZIP and open Terminal in its `WarRoomBot` folder.
2. Run `bash install.sh`. The default package index remains your Equinix Nexus mirror; connect to the corporate network/VPN. To deliberately use another trusted index, set `WARROOM_PIP_INDEX` when running the installer. No automatic public-index fallback was added.
3. Grant Accessibility access to Terminal, reopen it, and set your own `WARROOM_TEST_NUMBER` in the newly generated `.env`.
4. Sign into Zoom, join the bridge, and run `./watch.sh check` followed by `./watch.sh dry`.
5. Test actual greeting/call behavior with `./watch.sh start` in a controlled meeting. It calls only your configured test number. Stop with `./watch.sh stop`.

To create a DMG on macOS, run `bash tools/build_app.sh`. It compiles the native controller and bundled helper for Apple Silicon and Intel, packages a clean payload, signs and verifies the app, and creates `dist/War-Room-Bot-20261012.6.dmg`.

## Remaining validation and limits

The editing environment runs Linux; native compilation is delegated to macOS CI. The target Mac must still verify native-host permission, bundled-helper permission, read-only Check, roster/test rehearsal, Stop, and operation while the window is hidden. No CI check establishes a real Zoom call, shared-audio behavior, managed-device approval or the target Mac's Accessibility grant.

Zoom UI automation depends on the visible English-language controls expected by this project. Keep the Mac unlocked and awake. Validate both successful and unanswered calls, audio-share cleanup after Stop, and app start/stop on the target Mac. The hourly call ceiling is per watcher run; restarting resets it, while the disk call guard provides a shorter cross-run hold. There is no automatic dialling fallback to the next roster entry. Display names and phone-like display labels are not authenticated identities; leave roster-name trust disabled unless accepting that limitation.

For an existing installation, stop the watcher and back up your private files before replacing project source files. Do not replace your `.env`, roster or logs with the uploaded archive's copies.


## Target Mac results and Terminal launcher add-on

Versions 20261012.4 and 20261012.5 completed setup on the target Mac with 374 and 429 tests respectively. The installed app signature verified as valid on disk. The external helper was denied through the AppleScript app launch context and allowed through authorized Terminal. Direct execution from Terminal reached the menu. The user later confirmed that the installed app had no declared `CFBundleIdentifier`, and showed several simultaneously mounted DMGs with the same display name. Neither observation alone proves the cause of denied access.

The legacy Terminal launcher is retained in source for diagnosing older builds. The native DMG uses the Cocoa host and bundled helper instead. Apple supports signed AppleScript apps; this change does not establish that the old applet format was invalid. Apple documents that Accessibility prompting is asynchronous and that background detachment can complicate responsible-app attribution; keeping the native app as the worker's parent addresses that process design while still requiring target-Mac verification.
