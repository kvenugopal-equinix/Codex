-- War Room Bot: a thin menu around Contents/Resources/payload/app/wrb.sh. Every action is one wrb.sh call, so
-- everything here can also be done (and tested) by hand with that script.
-- No "property" or "global" that changes while it runs: an applet saves those into itself when it quits, which would
-- break its own signature.

on wrbPath()
	return (POSIX path of (path to me)) & "Contents/Resources/payload/app/wrb.sh"
end wrbPath

-- Runs one wrb.sh command. Returns {exit code, everything it printed}. Always through /bin/bash: a script inside a
-- quarantined app that macOS has not approved yet is killed when executed directly, but not when bash reads it.
on sh(args)
	try
		return {0, do shell script "/bin/bash " & (quoted form of my wrbPath()) & " " & args & " 2>&1"}
	on error msg number n
		return {n, msg}
	end try
end sh

on shOut(args)
	return item 2 of my sh(args)
end shOut

on shOk(args)
	return (item 1 of my sh(args)) is 0
end shOk

on showInfo(msg)
	activate
	display dialog msg with title "War Room Bot" buttons {"OK"} default button "OK" with icon note
end showInfo

on showWarning(msg)
	activate
	display dialog msg with title "War Room Bot" buttons {"OK"} default button "OK" with icon caution
end showWarning

-- ---------------------------------------------------------------------------------------------------------------

on run
	activate
	set appState to my shOut("state")
	if appState is "SETTING_UP" then
		if not my followSetup() then return
	else if appState is "NOT_INSTALLED" then
		set r to display dialog "Welcome to War Room Bot." & return & return & "First it needs to set itself up (about 2 minutes). It will:" & return & "  • copy its files to a folder called WarRoomBot in your home folder" & return & "  • install its Python packages from the Equinix Nexus server" & return & "  • build a small helper that reads the Zoom window" & return & return & "Your Mac must be on the Equinix network or VPN." with title "War Room Bot" buttons {"Cancel", "Set up"} default button "Set up" cancel button "Cancel" with icon note
		if not my runSetup() then return
	else if appState is "UPDATE_AVAILABLE" then
		set r to display dialog "A newer version of War Room Bot is included in this app. Update now? Your settings, roster and logs are kept." with title "War Room Bot" buttons {"Not now", "Update"} default button "Update" with icon note
		if button returned of r is "Update" then
			if my watcherIsOn() then
				my showWarning("The watcher is running. Choose Stop first, then Update / Repair.")
			else if not my runSetup() then
				return
			end if
		end if
	end if

	if not my ensureAccessibility() then return
	if not my ensureNumber() then return
	my mainMenu()
end run

-- ---------------------------------------------------------------------------------------------------------------
-- set-up

on runSetup()
	my sh("setup-bg")
	return my followSetup()
end runSetup

-- Shows a progress bar for a running set-up. Returns true when it finished cleanly.
on followSetup()
	set progress total steps to 6
	set progress completed steps to 0
	set progress description to "Setting up War Room Bot"
	set progress additional description to "Starting"
	set waited to 0
	try
		repeat
			delay 2
			set waited to waited + 2
			set p to my shOut("progress")
			if p starts with "DONE" then exit repeat
			set progress additional description to p
			try
				set progress completed steps to ((character 1 of p) as integer)
			end try
			if waited > 1500 then exit repeat
		end repeat
	on error number -128
		set progress total steps to 0
		my showInfo("Set-up carries on in the background. Open War Room Bot again in a couple of minutes.")
		return false
	end try
	set progress total steps to 0
	if my shOut("progress") is "DONE 0" then return true
	set why to my shOut("error")
	my showWarning("Set-up did not finish." & return & return & why & return & return & "Fix that and open War Room Bot again: it carries on where it stopped. The full log is in WarRoomBot/logs/setup.log in your home folder.")
	return false
end followSetup

-- ---------------------------------------------------------------------------------------------------------------
-- Accessibility

on ensureAccessibility()
	if my shOk("trusted") then return true
	repeat
		activate
		set r to display dialog "War Room Bot needs your permission to read the Zoom window and press its buttons (macOS calls this Accessibility)." & return & return & "1. Click Open Settings." & return & "2. Switch on War Room Bot in the list. If it is not there, click the + button and choose War Room Bot from Applications." & return & "3. Come back here and click Done." with title "War Room Bot" buttons {"Quit", "Open Settings"} default button "Open Settings" cancel button "Quit" with icon note
		my sh("accessibility")
		set r to display dialog "Switch War Room Bot on in the Accessibility list, then click Done." with title "War Room Bot" buttons {"Quit", "Done"} default button "Done" cancel button "Quit" with icon note
		if my shOk("trusted") then return true
		set r to display dialog "macOS does not show the permission as given yet. It sometimes needs the app to be reopened." & return & return & "Try again, or quit and open War Room Bot once more." with title "War Room Bot" buttons {"Quit", "Try again"} default button "Try again" cancel button "Quit" with icon caution
	end repeat
end ensureAccessibility

-- ---------------------------------------------------------------------------------------------------------------
-- test phone number

on ensureNumber()
	if my shOk("has-number") then return true
	return my askNumber()
end ensureNumber

-- Asks until the number is accepted. Returns false if the user cancels.
on askNumber()
	set curNum to my shOut("number")
	if curNum is "" then set curNum to "+"
	set msg to "Test phone number." & return & return & "War Room Bot calls only this number, and only for testing. Type it with + and the country code, e.g. +14155550123."
	repeat
		activate
		try
			set r to display dialog msg with title "War Room Bot" default answer curNum buttons {"Cancel", "Save"} default button "Save" cancel button "Cancel" with icon note
		on error number -128
			return false
		end try
		set typed to text returned of r
		set res to my sh("set-number " & quoted form of typed)
		if (item 1 of res) is 0 then return true
		set curNum to typed
		set msg to (item 2 of res) & return & return & "Type it with + and the country code, e.g. +14155550123."
	end repeat
end askNumber

-- ---------------------------------------------------------------------------------------------------------------
-- menu

on watcherIsOn()
	return (my shOut("status")) starts with "ON"
end watcherIsOn

on mainMenu()
	repeat
		set s to my shOut("status")
		if s is "" then set s to "unknown"
		set firstLine to paragraph 1 of s
		set choices to {"Check  (read-only: finds the meeting and lists who is in it)", "Dry run  (watch, but call nothing and play nothing)", "Start  (call the test number for each new visitor)", "Stop", "Status", "Recent activity", "Change test phone number", "Open data folder  (roster, settings, logs)", "Update / Repair", "Quit"}
		activate
		set picked to choose from list choices with title "War Room Bot" with prompt ("Version " & (my shOut("version")) & return & "Watcher: " & firstLine) default items {"Status"} OK button name "Go" cancel button name "Quit"
		if picked is false then
			if my quitOk() then return
		else
			set c to item 1 of picked
			if c starts with "Check" then
				my showResult("Check", my sh("check"))
			else if c starts with "Dry run" then
				my showResult("Dry run", my sh("dry"))
			else if c starts with "Start" then
				my doStart()
			else if c is "Stop" then
				my showResult("Stop", my sh("stop"))
			else if c is "Status" then
				my showInfo(my shOut("status"))
			else if c is "Recent activity" then
				my showInfo(my shOut("recent"))
			else if c starts with "Change test" then
				my askNumber()
			else if c starts with "Open data" then
				my sh("open-data")
			else if c starts with "Update" then
				if my watcherIsOn() then
					my showWarning("The watcher is running. Choose Stop first, then Update / Repair.")
				else
					try
						display dialog "This re-runs set-up: it repairs the Python packages and the helper, and installs a newer version if this app has one. Your settings, roster and logs are kept." with title "War Room Bot" buttons {"Cancel", "Run it"} default button "Run it" cancel button "Cancel" with icon note
						my runSetup()
					end try
				end if
			else if c starts with "Quit" then
				if my quitOk() then return
			end if
		end if
	end repeat
end mainMenu

-- Quitting leaves a running watcher on; say so, and let the user stop it instead.
on quitOk()
	if not my watcherIsOn() then return true
	activate
	try
		set r to display dialog "The watcher is still running. Quitting this app does not stop it." with title "War Room Bot" buttons {"Back", "Stop it and quit", "Leave it on and quit"} default button "Leave it on and quit" cancel button "Back" with icon note
	on error number -128
		return false
	end try
	if button returned of r is "Stop it and quit" then my showResult("Stop", my sh("stop"))
	return true
end quitOk

on showResult(heading, res)
	set txt to item 2 of res
	if txt is "" then set txt to "(nothing to report)"
	if (item 1 of res) is 0 then
		my showInfo(txt)
	else
		my showWarning(txt)
	end if
end showResult

on doStart()
	set n to my shOut("number")
	activate
	try
		set r to display dialog "Start watching?" & return & return & "For each new visitor in the Zoom meeting, War Room Bot will:" & return & "  • play the spoken welcome into the meeting, and" & return & "  • call " & n & " (your test number, nobody else)." & return & return & "Keep Zoom open with the meeting visible, and keep this Mac awake and unlocked." with title "War Room Bot" buttons {"Cancel", "Start"} default button "Start" cancel button "Cancel" with icon note
	on error number -128
		return
	end try
	my showResult("Start", my sh("start"))
end doStart
