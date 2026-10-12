"""Sets one setting in .env without touching anything else:

    python3 tools/set_env.py [--env PATH] KEY VALUE

Used by the War Room Bot app (its "test phone number" dialog) and usable by hand. Standard library only, so it runs
before the .venv exists. Only the settings in ALLOWED can be changed: the app can never switch on roster calling or
live mode through this. Prints what it did, never the value. Exit 0 = written, 2 = refused (nothing changed).
"""
import argparse
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path

# Same patterns as warroom/config.py (tests/test_set_env.py checks they have not drifted apart).
E164 = re.compile(r"\+[1-9][0-9]{6,14}")
EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


class Refused(Exception):
    pass


def _number(v: str) -> str:
    if v == "":
        return ""                                      # explicit clearing disables new test calls
    v = re.sub(r"[ \-().]", "", v)                       # people type "+65 9123 4567" or "+1 (415) 555-0123"
    if not E164.fullmatch(v):
        raise Refused("that is not an international number: use + then the country code then the number, "
                      "e.g. +14155550123")
    return v


def _email(v: str) -> str:
    v = v.strip()
    if v and not EMAIL.fullmatch(v):
        raise Refused("that is not an email address")
    return v


def _flag(v: str) -> str:
    v = v.strip().lower()
    if v not in ("true", "false"):
        raise Refused("use true or false")
    return v


def _contact_name(v: str) -> str:
    if any(ord(c) < 32 or 127 <= ord(c) < 160 for c in v):
        raise Refused("the Zoom contact name must be one line without control characters")
    v = v.strip()
    if len(v) > 200:
        raise Refused("the Zoom contact name must be at most 200 characters")
    return v


def _lookup(v: str) -> str:
    v = v.strip().lower()
    if v not in ("email", "name"):
        raise Refused("Contacts lookup must be email or name")
    return v


ALLOWED = {
    "WARROOM_TEST_NUMBER": _number,
    "WARROOM_TEST_ZOOM_EMAIL": _email,
    "WARROOM_ZOOM_INVITE": _flag,
    "WARROOM_ZOOM_CONTACT_LOOKUP": _lookup,
    "WARROOM_TEST_ZOOM_CONTACT": _contact_name,
}


def _comment(value: str) -> str:
    """Keep only a real dotenv comment, not a '#' inside a quoted display name."""
    quote, escaped = "", False
    for i, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#":
            return value[i:]
    return ""


def set_values(path: Path, values: dict) -> dict:
    """Validate the whole allowlisted update, then replace .env once. Returns key -> added/replaced.

    The first KEY= line is replaced where it stands (warroom/config.py's loader lets the first duplicate win, so an
    appended line would be ignored); its trailing "# comment" is kept. Clearing the test number blanks every
    active occurrence of that key so a duplicate cannot retain the saved number. With no such line the setting
    is appended."""
    checked = {}
    for key, value in values.items():
        if key not in ALLOWED:
            raise Refused(f"{key} cannot be changed here; allowed: {', '.join(sorted(ALLOWED))}")
        value = ALLOWED[key](value)
        if key == "WARROOM_TEST_ZOOM_CONTACT":
            checked[key] = shlex.quote(value) if value else ""
        else:
            if any(c in value for c in "\r\n#\"") or value.startswith("'") or value.endswith("'"):
                raise Refused("the value may not contain double quotes, # or line breaks")
            checked[key] = value
    if not checked:
        return {}
    lines = path.read_text().splitlines() if path.exists() else []
    results = {}
    for key, value in checked.items():
        clear_number = key == "WARROOM_TEST_NUMBER" and value == ""
        results[key] = "added"
        for i, line in enumerate(lines):
            s = line.strip()
            if s and not s.startswith("#") and "=" in s and s.split("=", 1)[0].strip() == key:
                comment = _comment(s.split("=", 1)[1])
                lines[i] = f"{key}={value}" + (f"  {comment}" if comment else "")
                results[key] = "replaced"
                if not clear_number:
                    break
        if results[key] == "added":
            lines.append(f"{key}={value}")
    # Write beside the target and swap it in, so a crash can never leave a half-written .env.
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600      # .env holds a phone number
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return results


def set_value(path: Path, key: str, value: str) -> str:
    """Backwards-compatible single-setting form of set_values()."""
    return set_values(path, {key: value})[key]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="set_env")
    p.add_argument("key")
    p.add_argument("value")
    p.add_argument("--env", type=Path, default=Path(__file__).resolve().parent.parent / ".env")
    a = p.parse_args(argv)
    try:
        what = set_value(a.env, a.key, a.value)
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(f"{what} {a.key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
