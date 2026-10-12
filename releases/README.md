# War Room Bot downloads

[Download War Room Bot 20261012.7 for macOS](War-Room-Bot-20261012.7.dmg?raw=true)

[Source ZIP](WarRoomBot-fixed-20261012.7.zip?raw=true) · [Build verification and installation steps](WarRoomBot-20261012.7-build.txt)

This version fixes discovery of detached Zoom Participants windows, formats new roster phone cells as Text, and adds Clear saved number. It keeps the app name **War Room Bot**, identifier `com.equinix.warroombot`, and the existing data folder.

Stop and quit the app before replacing it in Applications. Open the installed app and run **Update / Repair**, then wait for **Installation: ready**. Existing filled-in rosters are preserved; format their phone column as Text and re-enter any number whose leading `+` Excel removed.

Start **Dry run: roster** before a visitor joins and verify the selection before enabling real roster calls. Native builds and installation checks passed on the macOS runner; real Zoom calling on the target Mac remains to be verified.

Older downloads were retired because a documentation example contained a personal-number fragment. Previous Git commits and existing downloaded copies remain outside this release cleanup.
