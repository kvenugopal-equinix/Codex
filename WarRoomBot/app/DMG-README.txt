WAR ROOM BOT
============

1. Drag "War Room Bot" onto the Applications folder (the arrow in this window).
2. Eject this disk image and old War Room Bot disk images. Open the installed app from Applications.
3. Use Set up / Update / Repair. Wait for setup tests to finish successfully.
4. Request Accessibility permission in the app. Open Accessibility Settings is a separate action.
5. Use Diagnostics, Check meeting and a dry run before starting live calls.

You need:
  - a Mac on the Equinix network or VPN (the packages come only from the Equinix Nexus server)
  - Zoom, signed in as the bot account, with the war-room meeting open
  - the Apple developer tools; if they are missing, macOS offers to install them the first time


IF macOS SAYS IT "CANNOT BE OPENED" OR "COULD NOT VERIFY"
---------------------------------------------------------
This app is not signed with an Apple Developer ID, so macOS asks you to confirm it once.

  Easiest: open System Settings > Privacy & Security, scroll down to the message about
  "War Room Bot", click "Open Anyway", and confirm.

  Or, in Terminal, run this once and open the app again:

      xattr -dr com.apple.quarantine "/Applications/War Room Bot.app"

If your Mac is managed by IT and does not allow this, ask IT to approve the app, or use the terminal
install described in README.md instead.


THE ACCESSIBILITY PERMISSION
----------------------------
War Room Bot reads the Zoom window and presses its buttons, which macOS only allows with your say-so:
System Settings > Privacy & Security > Accessibility > switch on "War Room Bot". The app opens that
page for you. Diagnostics checks the native app and its bundled helper separately. Managed Macs may
require IT approval for new signed code. Terminal does not need to stay open to run the native app.


EVERY DAY
---------
Open War Room Bot and choose:
  Check          read-only: finds the meeting and lists who is in it
  Dry run: test number / Start: test number   rehearsal / real calls to the phone you enter for this run
  Preview on-duty roster   reports the selected engineer without calling
  Dry run: roster / Start: roster   rehearsal / confirmed real calls to the on-duty engineer
  Each Start form includes Phone only or Zoom Contacts + phone. Test mode asks for a fresh phone
  number and, when using both routes, a test contact name. Roster mode uses the selected roster name.
  Review the destinations before confirming Start; these choices are not saved.
  Stop           switches it off
  Recent activity / Status / Clear saved test number / Open data folder / Update / Repair

Closing the window hides the app while watching. Reopen it from the Dock or status item.
Quit offers Stop and quit, Hide and keep watching, or Cancel; the app stays alive while hidden.
It needs the Mac awake and unlocked, and the meeting visible on screen.

Everything lives in the WarRoomBot folder in your home folder (roster, settings, logs).


IF ACCESSIBILITY IS STILL DENIED
-------------------------------
Use Diagnostics in the installed app. It shows its bundle identifier, native permission and the exact
bundled helper path/result. Do not use a Terminal result as proof of the app's permission. Stop the
watcher before replacing the app. Native app launch and permissions must be verified on your Mac.
