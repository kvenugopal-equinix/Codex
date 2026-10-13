# War Room Bot 20261013.2

[Signed app ZIP](War-Room-Bot-20261013.2-app.zip?raw=true) · [Source ZIP](WarRoomBot-fixed-20261013.2.zip?raw=true) · [Build verification](WarRoomBot-20261013.2-build.txt) · [DMG](War-Room-Bot-20261013.2.dmg?raw=true)

**Start: test number** now asks for a number in a blank field every time. Saved or inherited numbers are never used as a fallback. The entered number is used only for that watcher run and is not saved to settings; Cancel or blank/invalid input starts nothing. **Clear saved test number** removes a value retained by earlier versions. Call logs may still record dialled numbers.

**Calling options → Zoom Contacts + phone** remains available. Roster mode searches Contacts by the selected on-duty engineer's roster **name**, sends an invitation, and calls that row's **phone** without waiting for acceptance. Test mode uses the phone entered for this run and an optional separately configured test contact name.

## Verified update for an existing installation

Use this Finder clean-copy method if the old DMG installation bounced without opening. It keeps **War Room Bot**, `com.equinix.warroombot`, `/Applications/War Room Bot.app`, and your existing private data folder. Terminal is needed only to prepare the update; the installed app runs independently.

1. Stop the watcher and quit War Room Bot.
2. Paste this entire block into Terminal. It downloads the pinned app ZIP, verifies its digest, saves an original backup, and checks the replacement's signature and visible window before opening Finder.

```bash
WRB_UPDATE_SCRIPT="$(mktemp /tmp/warroombot-update.XXXXXX)" &&
curl --fail --location --silent --show-error 'https://raw.githubusercontent.com/kvenugopal-equinix/Codex/dd9dfbc699c148e6b55ed7548f6842e0a3516df2/WarRoomBot/tools/prepare_app_update.py' --output "$WRB_UPDATE_SCRIPT" &&
/usr/bin/python3 "$WRB_UPDATE_SCRIPT" \
  --archive-url 'https://raw.githubusercontent.com/kvenugopal-equinix/Codex/b1e29893c5f1ff55efd99ef88d3b571048af7820/releases/War-Room-Bot-20261013.2-app.zip' \
  --sha256 '89bda655829af5f462ded3ee6f48a62affc55bc97ce0ca7f887a6d93e79536d1'

```

3. Drag the prepared **War Room Bot.app** onto the **Applications** shortcut and choose **Replace**. Use Finder's normal authentication if prompted. Run the final verification command printed by the script.
4. Open War Room Bot from **Applications**, choose **Update / Repair**, and wait for **Installation: ready**. Your roster, settings and logs are preserved.
5. Choose **Start: test number**. Enter a number in the blank field, review the destinations, and confirm the run. Use **Clear saved test number** after Stop to remove any old saved value.
6. For both contact routes, choose **Calling options → Go → Zoom Contacts + phone → Save**. Test mode also needs a test contact name; roster mode uses the selected engineer's name.
7. For roster calls, make the roster **name** match one existing Zoom contact. Keep **phone** cells formatted as **Text** with the full `+` and country code. Preview the on-duty roster, then use **Dry run: roster** before **Start: roster**. Start before a new visitor joins; people already present form the baseline.

689 tests passed on Linux and macOS. The universal build, real window launches, and Finder upgrade from the published 20261013.1 app all passed on macOS. Actual Zoom invitations and phone calls still need a live rehearsal on your Mac; no calls were placed during these checks. Signing is ad-hoc integrity signing, without Developer ID notarization.

The prior version 7 and 20261013.1 files remain available for rollback. Older affected downloads were retired because a documentation example contained a personal-number fragment; previous Git commits and existing downloaded copies remain outside that cleanup.
