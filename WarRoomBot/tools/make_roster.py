"""Writes a placeholder roster.xlsx (sheets "roster" and "README"). Never overwrites an existing file.

    .venv/bin/python tools/make_roster.py [path]

Placeholder rows (a name starting with "<" or a phone containing "X") are ignored by the bot until you replace them.
"""
import sys
from pathlib import Path

HEADER = ["name", "zoom_email", "phone", "timezone", "days", "shift_start", "shift_end", "priority", "active", "notes"]
ROWS = [
    ["<Engineer 1 - replace>", "<engineer1@example.com>", "+XXXXXXXXXXX", "Asia/Singapore", "Mon-Fri", "09:00", "18:00", 1, "yes", ""],
    ["<Engineer 2 - replace>", "<engineer2@example.com>", "+XXXXXXXXXXX", "Asia/Singapore", "Mon-Fri", "18:00", "03:00", 1, "yes", "an overnight shift ends the next morning"],
    ["<Engineer 3 - replace>", "<engineer3@example.com>", "+XXXXXXXXXXX", "Asia/Singapore", "Sat-Sun", "00:00", "23:59", 2, "yes", ""],
]
README = [
    ["Column", "Meaning"],
    ["name", "Engineer's name. A name that starts with '<' marks a placeholder row, which the bot ignores."],
    ["zoom_email", "Their Zoom sign-in email. Used only for optional Zoom contact invitations; Accessibility does not expose participant email."],
    ["phone", "International format, +<country code><number>. A phone containing X marks a placeholder row."],
    ["timezone", "IANA name, e.g. Asia/Singapore or America/New_York. The shift times are in this zone."],
    ["days", "Mon-Fri, Sat-Sun, a list such as Mon,Wed,Fri, or daily."],
    ["shift_start / shift_end", "HH:MM, 24 hour. If the end is earlier than the start the shift runs overnight."],
    ["priority", "1 is called first. Lowest number is selected; automatic fallback dialling is not implemented."],
    ["active", "yes or no. Leave a row in place and set no to take someone off without deleting them."],
    ["notes", "Free text."],
    ["", ""],
    ["Test mode", "While WARROOM_TARGET_MODE=test the bot ignores every number here and dials only WARROOM_TEST_NUMBER."],
]


def main(argv) -> int:
    from openpyxl import Workbook
    path = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "roster.xlsx"
    if path.exists():
        print(f"{path} already exists; left alone")
        return 0
    wb = Workbook()
    ws = wb.active
    ws.title = "roster"
    ws.append(HEADER)
    for r in ROWS:
        ws.append(r)
    for col, width in zip("ABCDEFGHIJ", (26, 28, 18, 18, 10, 12, 12, 9, 8, 40)):
        ws.column_dimensions[col].width = width
    doc = wb.create_sheet("README")
    for r in README:
        doc.append(r)
    doc.column_dimensions["A"].width = 24
    doc.column_dimensions["B"].width = 110
    wb.save(path)
    print(f"wrote {path} with placeholder rows: replace them before using TARGET_MODE=roster")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
