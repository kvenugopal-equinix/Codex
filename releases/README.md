# War Room Bot 20261013.3

[App ZIP](War-Room-Bot-20261013.3-app.zip?raw=true) · [Source ZIP](WarRoomBot-fixed-20261013.3.zip?raw=true) · [Build verification](WarRoomBot-20261013.3-build.txt) · [DMG](War-Room-Bot-20261013.3.dmg?raw=true)

**Start: roster** and **Start: test number** now include the **Phone only / Zoom Contacts + phone** choice in the Start dialog. There is no separate Calling options step. Review the destinations and confirm to start; Cancel starts nothing.

Roster mode uses the selected on-duty engineer's Excel **name** for Zoom Contacts and **phone** for the call. Test mode opens a blank phone field every time; choosing both routes also requires a test contact display name. These choices apply only to that watcher run and are not saved to settings.

This release fixes the handoff after a successful Zoom Contacts invitation: if Zoom opens the next Invite window but reports an Accessibility error, the bot checks whether the window actually opened before retrying. An already open window continues to phone setup without another opener press. Contact invitation and phone Call submission remain single attempts.

**Shift changes need no restart in roster mode.** Each new visitor escalation reloads the saved roster and selects the engineer on duty at that time, using the row's timezone and priority. A shift change alone does not trigger a call. An in-progress call keeps its original target; the next new visitor uses the new shift. Saved destination and shift edits also apply at the next escalation. Restart if adding people who need to be recognized as support: the support-recognition list is loaded when the watcher starts.

## Verified update for an existing installation

Use this Finder preparation method for the installation that bounced when copied from a DMG. It keeps **War Room Bot**, `com.equinix.warroombot`, `/Applications/War Room Bot.app`, and your existing private data folder. Terminal is needed only to prepare the update; the installed app runs independently.

1. Stop the watcher and quit War Room Bot.
2. Paste this entire block into Terminal. It downloads the pinned app ZIP, verifies its digest, retains an original backup, and checks the replacement's signature and visible window before opening Finder.

```bash
WRB_UPDATE_SCRIPT="$(mktemp /tmp/warroombot-update.XXXXXX)" &&
curl --fail --location --silent --show-error 'https://raw.githubusercontent.com/kvenugopal-equinix/Codex/b47fd6fc6f5367be8066c48a79fcbf907ffdc7ca/WarRoomBot/tools/prepare_app_update.py' --output "$WRB_UPDATE_SCRIPT" &&
/usr/bin/python3 "$WRB_UPDATE_SCRIPT" \
  --archive-url 'https://raw.githubusercontent.com/kvenugopal-equinix/Codex/b021752f68ae45d4f6482beec82677858f88280a/releases/War-Room-Bot-20261013.3-app.zip' \
  --sha256 '66ee95db5da4b691de8691bbee213ed5364cdaeb13608ffbefbc86d97a682f0a'
```

3. Drag the prepared **War Room Bot.app** onto the **Applications** shortcut and choose **Replace**. Use Finder's normal authentication if prompted. Keep the app quit while you run the final verification command printed by the script.
4. Open War Room Bot from **Applications**, choose **Update / Repair**, and wait for **Installation: ready**. Your roster, settings and logs are preserved.
5. Choose **Start: roster → Go**, choose **Zoom Contacts + phone** in that dialog, then review and confirm. For testing, choose **Start: test number → Go** and enter the test phone and contact name in its dialog.

Keep roster **phone** cells formatted as **Text**, including `+` and country code. Match each roster **name** to one existing Zoom contact. Start the watcher before a new visitor joins; people already present form the baseline. **Clear saved test number** remains available after Stop to remove a value retained by earlier versions.

781 tests passed on Linux and macOS. The universal arm64/x86_64 build, actual native Start forms and Cancel behavior, window launches from Applications, and Finder upgrade from the published 20261013.2 app all passed on macOS. The Contacts-to-phone sequence was tested with simulated Zoom; a combined live call on your Mac remains to be verified. No real calls or invitations were placed during validation. Signing is ad-hoc integrity signing, without Developer ID notarization.

Previous releases remain available for rollback. Older affected downloads were retired because a documentation example contained a personal-number fragment; previous Git commits and existing downloaded copies remain outside that cleanup.
