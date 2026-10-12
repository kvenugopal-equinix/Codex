"""Create a roster template with phone cells formatted as Excel Text.

User-edited rosters are preserved. An unchanged generated placeholder template
can have its phone formatting repaired without changing any cell values.

    .venv/bin/python tools/make_roster.py [path]

Placeholder rows (a name starting with "<" or a phone containing "X") are ignored by the bot until you replace them.
"""
import sys
import os
from pathlib import Path
import stat
import tempfile
from zipfile import BadZipFile

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
    ["phone", "Keep this column formatted as Text and enter +<country code><number>. If Excel already removed '+', change the format to Text and re-enter the full international number. A phone containing X marks a placeholder row."],
    ["timezone", "IANA name, e.g. Asia/Singapore or America/New_York. The shift times are in this zone."],
    ["days", "Mon-Fri, Sat-Sun, a list such as Mon,Wed,Fri, or daily."],
    ["shift_start / shift_end", "HH:MM, 24 hour. If the end is earlier than the start the shift runs overnight."],
    ["priority", "1 is called first. Lowest number is selected; automatic fallback dialling is not implemented."],
    ["active", "yes or no. Leave a row in place and set no to take someone off without deleting them."],
    ["notes", "Free text."],
    ["", ""],
    ["Test mode", "While WARROOM_TARGET_MODE=test the bot ignores every number here and dials only WARROOM_TEST_NUMBER."],
]


def _format_phone_cells(sheet):
    sheet.column_dimensions["C"].number_format = "@"
    for row in range(2, sheet.max_row + 1):
        sheet.cell(row=row, column=3).number_format = "@"


def _repair_unchanged_template(path):
    """Only repair the exact placeholder data shipped by this generator."""
    if path.suffix.lower() != ".xlsx" or path.is_symlink():
        return False
    from openpyxl import load_workbook
    try:
        book = load_workbook(path)
    except (OSError, ValueError, BadZipFile):
        return False  # An unrecognized existing file is never replaced by the generator.
    try:
        if set(book.sheetnames) != {"roster", "README"}:
            return False
        sheet = book["roster"]
        values = [[value if value is not None else "" for value in row] for row in sheet.values]
        if values != [HEADER] + ROWS:
            return False
        if sheet.column_dimensions["C"].number_format == "@" and all(
                sheet.cell(row=row, column=3).number_format == "@"
                for row in range(2, sheet.max_row + 1)):
            return False
        _format_phone_cells(sheet)
        original_mode = stat.S_IMODE(path.stat().st_mode)
        fd, temporary = tempfile.mkstemp(prefix=".roster-phone-format-", suffix=".xlsx", dir=str(path.parent))
        os.close(fd)
        try:
            book.save(temporary)
            os.chmod(temporary, original_mode)
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return True
    finally:
        book.close()


def main(argv) -> int:
    from openpyxl import Workbook
    path = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "roster.xlsx"
    if path.exists():
        if _repair_unchanged_template(path):
            print(f"{path}: repaired placeholder phone cells to Text; all values preserved")
        else:
            print(f"{path} already exists; left alone. Keep its phone column as Text, including the + country-code prefix.")
        return 0
    wb = Workbook()
    ws = wb.active
    ws.title = "roster"
    ws.append(HEADER)
    for r in ROWS:
        ws.append(r)
    _format_phone_cells(ws)
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
