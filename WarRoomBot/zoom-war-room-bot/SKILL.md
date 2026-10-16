---
name: zoom-war-room-bot
description: Use when helping operate the War Room Bot in a Zoom bridge, checking a new visitor, selecting the on-duty engineer, inviting or calling support, or reviewing the activity log.
---

# Zoom War Room Bot

Act as the bridge operator's assistant. Apply the workflow below only with live,
authorized tools that are actually connected to this agent. Distinguish a tool's
confirmed result from an action you merely requested. If a required tool is
unavailable, say what cannot be done and give the operator the corresponding
War Room Bot action.

## Establish the operating state

1. Check the running bot's status and version when a status tool is available.
   The Mac bot's `status` command is `~/WarRoomBot/watch.sh status`.
2. Identify the active Zoom meeting, selected route (`phone` or
   `contacts-phone`), and mode (`test` or `roster`) from a current source.
3. Treat requests to check, summarize, or preview as read-only. Never start a
   live run because a user asked for an explanation.
4. For a test run, require a number supplied for this run. For a
   `contacts-phone` test, also require one exact Zoom Contact name. Do not
   reuse a previously saved test number.
5. For a live roster run, show the current selected engineer, phone number,
   route, and consequences; require the operator's explicit start and
   confirmation for that run. Respect Zoom's configured tool approvals.

## Handle a new visitor

1. Use a verified real-time participant source. The first successful read is
   the baseline; people already present are not new arrivals. A failed read
   does not prove anyone left. Transcripts and chat history are not a live
   participant source.
2. Handle each new non-support arrival once. If a welcome output tool is
   connected, play the welcome and record its confirmed outcome. The Mac
   bot's spoken welcome has not yet been verified on the target Mac; never
   report success from intent alone.
3. Wait the configured grace period (10 seconds by default), then refresh
   participants and reload the roster. If the visitor left, do not escalate.
   If a fresh read is unavailable, report uncertainty and do not independently
   invite or call.
4. Select only the current highest-priority on-duty engineer. Do not invent a
   substitute or automatically try the next engineer.
5. If exactly one non-bot participant's displayed name matches that selected
   engineer after trimming surrounding spaces and ignoring case, skip both
   the Zoom Contact invitation and phone call. This is duplicate-contact
   avoidance, not identity verification. Duplicate names, another roster
   name, or stale participant data cannot justify the skip.
6. Enforce the configured maximum calls per rolling hour (3 by default) and
   prevent duplicate escalation for the same arrival. With the
   `contacts-phone` route, invite only one exact matching Zoom Contact.
   Report missing or ambiguous contacts. The separate phone call may proceed
   only when its roster number, live-run authorization, and tool are valid.
   With the `phone` route, do not send a Contacts invitation.

## Record and report

- Ask the bot's supported logging tool to create one event for each handled
  arrival, with its generated `event_id`, visitor, meeting, selected engineer,
  welcome result, invitation result, phone result, and times. Never invent an
  event ID or claim that an unconnected agent wrote the bot's files.
- The local `~/WarRoomBot/logs/join_log.csv` is the durable journal. The bot
  creates and updates a selected `.xlsx` workbook at a Finder-synced OneDrive
  location; it mirrors the journal and preserves operator `Comments`. An
  existing workbook does not prove new rows are being published.
- If status reports `Activity runtime patch: missing or changed`, or Python
  reports that `activity_report` cannot import `_locked` from `joinlog`, report
  the mixed runtime and direct the operator to repair it before relying on
  workbook updates.
- Reply with the observed state and timestamp, decision and reason, actions
  attempted, confirmed outcomes, and CSV/workbook results separately. Keep
  meeting links, phone numbers, and roster details in the authorized context.

## Tool boundary

The existing Mac bot uses macOS Accessibility and has no agent-callable API.
This skill does not grant access to live participant events, computer-audio
sharing, Zoom Contact invitations, in-meeting phone calling, the roster, or
local files. Use those actions only after a corresponding connected tool has
been verified. Otherwise, guide the operator through **Check meeting**,
**Preview on-duty roster**, **Dry run: roster**, **Start: roster**, and
**Activity log** in the Mac app.
