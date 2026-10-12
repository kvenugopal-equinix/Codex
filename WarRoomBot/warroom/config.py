"""Env-driven settings and call-safety gates (see MAC_SETUP.md section 6)."""
import math
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
E164 = re.compile(r"\+[1-9][0-9]{6,14}")      # ASCII digits only; str \d would accept other scripts
EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")   # a Zoom account address
TRUE, FALSE = ("1", "true", "yes", "on"), ("0", "false", "no", "off")


class ConfigError(ValueError):
    """A setting is unusable. Raised instead of guessing, so a typo can never open a safety gate."""


def _flag(name: str, default: bool) -> bool:
    """An unset, blank or unrecognised value keeps `default`. Every gate's default is the safe state
    (dry-run on, live calling off), so a typo such as 'ture' or '"false"' cannot open a gate."""
    v = os.environ.get(name, "").strip().strip("\"'").strip().lower()
    return True if v in TRUE else False if v in FALSE else default


def _number(name: str, default: float, minimum: float, whole: bool = False) -> float:
    """A finite number >= minimum from the environment; blank means `default`; anything else is an error."""
    raw = os.environ.get(name, "").strip().strip("\"'").strip()
    try:
        v = int(raw or default) if whole else float(raw or default)
    except ValueError:
        raise ConfigError(f"{name}={raw!r} is not a number") from None
    if not math.isfinite(v) or v < minimum:
        raise ConfigError(f"{name}={v} must be a finite number of at least {minimum:g}")
    return v


def load_dotenv(path: Path = BASE / ".env") -> None:
    """Real environment variables win over .env, and for a duplicated key the first line wins."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                raise ConfigError(f"invalid key in {path.name}: {k!r}")
            lexer = shlex.shlex(v, posix=True)
            lexer.whitespace_split = True
            try:
                value = " ".join(lexer)
            except ValueError as e:
                raise ConfigError(f"invalid value for {k} in {path.name}: {e}") from None
            os.environ.setdefault(k, value)


@dataclass(frozen=True)
class Settings:
    dry_run: bool
    live_calling: bool
    target_mode: str  # "test" or "roster"
    test_number: str
    allow_roster_calls: bool
    roster_path: Path
    join_log_path: Path
    voice_enabled: bool = True
    voice_in_dry_run: bool = False
    voice_name: str = ""
    voice_message: str = ""
    voice_route: str = "share"          # "share": played into the meeting as Zoom shared computer sound; "local": this Mac's speakers only
    call_timeout: float = 60.0
    # Join watcher (`watch`)
    poll_seconds: float = 3.0           # how often the participant list is read
    grace_seconds: float = 10.0         # a visitor must still be there this long after joining before anyone is called
    max_calls_per_hour: int = 3         # watcher-level ceiling on calls it places, on top of the call guard
    trust_display_names: bool = False   # treat a participant whose name equals a roster name as support (spoofable)
    skip_if_support: bool = True        # do not call when an engineer is already in the meeting
    ignore_names: tuple = ()            # lower-case display names that are never visitors (note-takers, other bots)
    zoom_invite: bool = False           # also invite the engineer as a Zoom contact (Invite > Contacts), off by default
    test_zoom_email: str = ""           # test mode invites only this Zoom account

    def gates(self) -> str:
        """One line for the operator: the values that decide whether a real call can happen."""
        return (f"dry_run={self.dry_run} live_calling={self.live_calling} target_mode={self.target_mode} "
                f"roster_calls={self.allow_roster_calls} dial_method={os.environ.get('WARROOM_DIAL_METHOD', 'ui')} "
                f"zoom_invite={self.zoom_invite}")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        mode = os.environ.get("WARROOM_TARGET_MODE", "").strip().strip("\"'").lower() or "test"
        if mode not in ("test", "roster"):
            raise ConfigError(f"WARROOM_TARGET_MODE={mode!r} is not 'test' or 'roster'")
        route = os.environ.get("WARROOM_VOICE_ROUTE", "").strip().strip("\"'").lower() or "share"
        if route not in ("share", "local"):
            raise ConfigError(f"WARROOM_VOICE_ROUTE={route!r} is not 'share' or 'local'")
        try:
            timeout = float(os.environ.get("WARROOM_CALL_TIMEOUT", "").strip() or "60")
        except ValueError:
            raise ConfigError("WARROOM_CALL_TIMEOUT is not a number") from None
        if not math.isfinite(timeout) or timeout < 5:
            raise ConfigError(f"WARROOM_CALL_TIMEOUT={timeout} must be a finite number of at least 5 seconds")
        zoom_email = os.environ.get("WARROOM_TEST_ZOOM_EMAIL", "").strip().strip("\"'").strip()
        if zoom_email and not EMAIL.fullmatch(zoom_email):
            raise ConfigError("WARROOM_TEST_ZOOM_EMAIL is not an email address")
        return cls(
            dry_run=_flag("WARROOM_DRY_RUN", True),
            live_calling=_flag("WARROOM_LIVE_CALLING", False),
            target_mode=mode,
            test_number=os.environ.get("WARROOM_TEST_NUMBER", ""),
            allow_roster_calls=_flag("WARROOM_ALLOW_ROSTER_CALLS", False),
            roster_path=Path(os.environ.get("WARROOM_ROSTER", BASE / "roster.xlsx")),
            join_log_path=Path(os.environ.get("WARROOM_JOIN_LOG", BASE / "logs" / "join_log.csv")),
            voice_enabled=_flag("WARROOM_VOICE", True),
            voice_in_dry_run=_flag("WARROOM_VOICE_IN_DRY_RUN", False),
            voice_name=os.environ.get("WARROOM_VOICE_NAME", ""),
            voice_message=os.environ.get("WARROOM_VOICE_MESSAGE", ""),
            voice_route=route,
            call_timeout=timeout,
            poll_seconds=_number("WARROOM_POLL_SECONDS", 3.0, 1.0),
            grace_seconds=_number("WARROOM_GRACE_SECONDS", 10.0, 0.0),
            max_calls_per_hour=_number("WARROOM_MAX_CALLS_PER_HOUR", 3, 1, whole=True),
            trust_display_names=_flag("WARROOM_TRUST_DISPLAY_NAMES", False),
            skip_if_support=_flag("WARROOM_SKIP_IF_SUPPORT_PRESENT", True),
            ignore_names=tuple(n.strip().lower() for n in os.environ.get("WARROOM_IGNORE_NAMES", "").split(",")
                               if n.strip()),
            zoom_invite=_flag("WARROOM_ZOOM_INVITE", False),
            test_zoom_email=zoom_email,
        )
