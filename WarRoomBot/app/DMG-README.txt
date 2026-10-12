WAR ROOM BOT
============

1. Drag "War Room Bot" onto the Applications folder (the arrow in this window).
2. Open it from Applications. Follow the dialogs: set-up (about 2 minutes), the Accessibility
   permission, and your test phone number.

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
page for you. If you replace the app with a newer one, switch it off and on again.


EVERY DAY
---------
Open War Room Bot and choose:
  Check          read-only: finds the meeting and lists who is in it
  Dry run        watches, but calls nothing and plays nothing
  Start          for each new visitor: plays the welcome in the meeting and calls your TEST number
  Stop           switches it off
  Recent activity / Status / Change test phone number / Open data folder / Update / Repair

The watcher keeps running when you quit the app; open the app and choose Stop to switch it off.
It needs the Mac awake and unlocked, and the meeting visible on screen.

Everything lives in the WarRoomBot folder in your home folder (roster, settings, logs).
