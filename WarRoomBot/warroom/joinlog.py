"""Append-only join log for reporting."""
import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

FIELDS = ["joined_at_utc", "joined_at_local", "timezone", "meeting_id", "participant_name",
          "participant_id", "role", "welcome_posted", "welcome_voice", "engineer_called", "engineer_name",
          "call_started_utc", "call_answered", "notes", "zoom_invited"]


def _migrate(path: Path) -> list:
    """A log written before a column was added has a header that is a strict prefix of FIELDS. Rewrite it with the
    full header (old rows padded) so new rows line up. Returns the header the file ends up with; if the rewrite is
    not possible (file open elsewhere, read-only folder) the old header comes back and the caller writes to that."""
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    old = rows[0] if rows else []
    if not old or old == FIELDS or old != FIELDS[:len(old)]:
        return old or FIELDS
    tmp = path.with_name(path.name + ".migrating")
    try:
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(FIELDS)
            for r in rows[1:]:
                w.writerow(r + [""] * (len(FIELDS) - len(r)))
        os.replace(tmp, path)
        return FIELDS
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return old


def log_join(path: Path, tz: str = "Asia/Singapore", **fields) -> dict:
    now = datetime.now(timezone.utc)
    row = {k: "" for k in FIELDS}
    row.update(joined_at_utc=now.isoformat(timespec="seconds"),
               joined_at_local=now.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds"),
               timezone=tz, **fields)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    header = FIELDS if new else _migrate(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")   # an older header just lacks the newest columns
        if new:
            w.writeheader()
        w.writerow(row)
    return row
