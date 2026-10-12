# War Room Bot 20261013.1

[Signed app ZIP](War-Room-Bot-20261013.1-app.zip?raw=true) · [Source ZIP](WarRoomBot-fixed-20261013.1.zip?raw=true) · [Build verification](WarRoomBot-20261013.1-build.txt) · [DMG](War-Room-Bot-20261013.1.dmg?raw=true)

**Calling options → Zoom Contacts + phone** now searches Contacts by the selected on-duty engineer's roster **name**, sends an invitation, and calls the same row's **phone** without waiting for acceptance. No email is sent. Missing or ambiguous Contacts names are reported while the phone call proceeds. Test destinations are user-entered and start blank.

## Verified update for an existing installation

Use this Finder clean-copy method if the old DMG installation bounced without opening. It keeps **War Room Bot**, `com.equinix.warroombot`, `/Applications/War Room Bot.app`, and your existing private data folder. Terminal is needed only to prepare the update; the installed app runs independently.

1. Stop the watcher and quit War Room Bot.
2. Paste this entire block into Terminal. It downloads the pinned app ZIP, verifies its digest, saves an original backup, and checks the replacement's signature and visible window before opening Finder.

```bash
WRB_UPDATE_SCRIPT="$(mktemp /tmp/warroombot-update.XXXXXX)" &&
curl --fail --location --silent --show-error 'https://raw.githubusercontent.com/kvenugopal-equinix/Codex/946edb9379f311efdf8f8cce6c84045d89688d0b/WarRoomBot/tools/prepare_app_update.py' --output "$WRB_UPDATE_SCRIPT" &&
/usr/bin/python3 "$WRB_UPDATE_SCRIPT" \
  --archive-url 'https://raw.githubusercontent.com/kvenugopal-equinix/Codex/e1c37fef96cdc43559aa126337250343faf4e701/releases/War-Room-Bot-20261013.1-app.zip' \
  --sha256 'e3a015b54c7c6f653b72a5db881b40b3bbdeff4bbb598a0c72da6b680b31a31d'

```

3. Drag the prepared **War Room Bot.app** onto the **Applications** shortcut and choose **Replace**. Use Finder's normal authentication if prompted. Run the final verification command printed by the script.
4. Open War Room Bot from **Applications**, choose **Update / Repair**, and wait for **Installation: ready**. Your roster, settings and logs are preserved.
5. Choose **Calling options → Go → Zoom Contacts + phone → Save**.
6. Make the roster **name** match one existing Zoom contact. Keep **phone** cells formatted as **Text** with the full `+` and country code.
7. Use **Preview on-duty roster**, then **Dry run: roster**. Start **Start: roster** before a new visitor joins when ready for real calls. People already present form the watcher's baseline.

669 tests passed on Linux and macOS. The universal build, real window launches, and upgrade from the published version 7 app all passed on macOS. Actual Zoom invitations and phone calls still need a live rehearsal on your Mac; no calls were placed during these checks. Signing is ad-hoc integrity signing, without Developer ID notarization.

The prior version 7 files remain available for rollback. Older affected downloads were retired because a documentation example contained a personal-number fragment; previous Git commits and existing downloaded copies remain outside that cleanup.
