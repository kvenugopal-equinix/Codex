"""Join watcher: reads the Zoom participant list on a timer and escalates when a visitor joins.

Poll and diff. The first good read is the baseline: people already in the meeting are never greeted, so a
restart does not call for the whole room. After that, each new visitor gets the spoken welcome, a grace
period, a re-check (still there? an engineer already in?), and then the call-out. The watcher never presses
anything itself; it only reads, and hands the decision to `escalate`, which goes through the gated dialer.

Who counts as a visitor (never by display name alone, because names are spoofable):
  me        the bot's own row
  ignored   names listed in WARROOM_IGNORE_NAMES (note-takers, other bots)
  support   a participant shown by a phone number that is on the roster, is the test number, or is a number
            this run dialled; and, only if
            WARROOM_TRUST_DISPLAY_NAMES is on, a roster name
  visitor   everyone else
"""
import re
import time
from collections import Counter
from typing import Callable, Optional

from .ui_backend import UiError

HOUR = 3600.0
LEAVE_READS = 2           # a name must be missing from this many good reads in a row before it counts as gone
QUIET_AFTER_BAD = 10      # a run of failed reads is reported at its 1st and this many, then every 10x as often
RECHECK_TRIES = 3
CALLEE_WAIT = 10.0        # after an answered call, how long to look for the engineer appearing in the list


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _same_number(a: str, b: str) -> bool:
    """Zoom may show a callee without the country code, so one number may end the other (7+ digits)."""
    a, b = _digits(a), _digits(b)
    return len(a) >= 7 and len(b) >= 7 and (a.endswith(b) or b.endswith(a))


class Watcher:
    """`read() -> [UiParticipant]` (raises UiError on a bad read), `start_voice() -> handle | None`,
    `escalate(name, voice) -> (DialResult, number)`, `log_skip(name, voice, why)`."""

    def __init__(self, settings, shifts, read: Callable, escalate: Callable, log_skip: Callable,
                 start_voice: Callable = lambda: None, *, sleep=None, clock=None, out=print):
        self.s = settings
        self.read, self.escalate, self.log_skip, self.start_voice = read, escalate, log_skip, start_voice
        self.sleep = sleep or (lambda sec: time.sleep(sec))
        self.clock = clock or (lambda: time.monotonic())
        self.out = out
        real = [x for x in shifts if not x.is_placeholder]
        self.phones = {_digits(x.phone) for x in real if _digits(x.phone)}
        if settings.test_number:
            self.phones.add(_digits(settings.test_number))
        self.support_names = {x.name.strip().lower() for x in real} if settings.trust_display_names else set()
        self.known: Counter = Counter()       # visitor names (with multiplicity) already dealt with or present at start
        self.gone: Counter = Counter()        # consecutive good reads in which a known name was short
        self.baselined = False
        self.bad = 0
        self.last: list = []                  # the most recent good read
        self.interrupted = False             # Ctrl-C landed while a call was being placed
        self.calls: list = []                 # clock() of each call this watcher placed, for the hourly ceiling

    # ------------------------------------------------------------ classification
    def kind(self, p) -> str:
        if p.is_me:
            return "me"
        name = p.display_name.strip().lower()
        if name in self.s.ignore_names:
            return "ignored"
        if name in self.support_names or any(_same_number(p.phone_number, n) for n in self.phones):
            return "support"
        return "visitor"

    def _visitors(self, people) -> Counter:
        return Counter(p.display_name for p in people if self.kind(p) == "visitor")

    # ------------------------------------------------------------ reading
    def _read(self) -> Optional[list]:
        """A good read, or None. A failed read is a glitch and never evidence that anyone left (lesson 4). The watcher
        never gives up on its own: a window that is hidden for a while (another desktop, a lock, a share) comes back,
        and whoever joined meanwhile is then greeted. Only Ctrl-C ends it."""
        try:
            people = self.read()
        except UiError as e:
            self.bad += 1
            if self.bad in (1, QUIET_AFTER_BAD) or self.bad % (QUIET_AFTER_BAD * 10) == 0:
                self.out(f"read failed ({self.bad} in a row, still watching): {e}")
            return None
        if self.bad > 1:
            self.out(f"reading the meeting again after {self.bad} failed reads")
        self.bad = 0
        self.last = people
        return people

    def poll(self) -> None:
        people = self._read()
        if people is not None:
            self.step(people)

    def run(self, max_polls: Optional[int] = None) -> None:
        n = 0
        while max_polls is None or n < max_polls:
            self.poll()
            n += 1
            self.sleep(self.s.poll_seconds)

    # ------------------------------------------------------------ diffing
    def step(self, people: list) -> None:
        now = self._visitors(people)
        if not self.baselined:
            self.known, self.baselined = Counter(now), True
            here = ", ".join(repr(n) for n in sorted(now.elements())) or "nobody else"
            self.out(f"watching. Already in the meeting (not greeted): {here}")
            return
        new = []
        for name in sorted(set(self.known) | set(now)):
            have, seen = now[name], self.known[name]
            if have > seen:
                new += [name] * (have - seen)
                self.known[name], self.gone[name] = have, 0
            elif have == seen:
                self.gone[name] = 0
            else:
                self.gone[name] += 1
                if self.gone[name] >= LEAVE_READS:
                    self.known[name], self.gone[name] = have, 0
            if not self.known[name]:
                del self.known[name]
        if new:
            try:
                self.handle(new)
            except Exception as e:      # a bug while escalating must not end a watch that may run for hours
                self.out(f"ERROR: {type(e).__name__}: {e}. These visitors were NOT escalated: "
                         + ", ".join(repr(n) for n in new))

    # ------------------------------------------------------------ one visitor
    def _calls_this_hour(self) -> int:
        cutoff = self.clock() - HOUR
        self.calls = [t for t in self.calls if t > cutoff]
        return len(self.calls)

    def _recheck(self) -> Optional[list]:
        for i in range(RECHECK_TRIES):
            people = self._read()
            if people is not None:
                return people
            if i + 1 < RECHECK_TRIES:
                self.sleep(self.s.poll_seconds)
        return None

    def handle(self, names: list) -> None:
        """One or more visitors who joined in the same poll share one greeting and one call."""
        self.out("VISITOR JOINED: " + ", ".join(repr(n) for n in names))
        if self._calls_this_hour() >= self.s.max_calls_per_hour:
            self._skip(names, None, f"call limit reached ({self.s.max_calls_per_hour} in the last hour)")
            return
        voice = self.start_voice()
        self.sleep(self.s.grace_seconds)
        people = self._recheck()
        present = list(names)
        if people is None:
            self.out("WARNING: could not re-read the participant list after the grace period; calling anyway")
        else:
            have = self._visitors(people)
            present = [n for n in names if have[n] > 0]
            self._skip([n for n in names if n not in present], voice, "left during the grace period")
            if not present:
                return
            helpers = [repr(p.display_name) for p in people if self.kind(p) == "support"]
            if helpers and self.s.skip_if_support:
                self._skip(present, voice, f"an engineer is already in the meeting ({', '.join(helpers)})")
                return
        before = Counter(p.display_name for p in (people or self.last) if not p.is_me)
        first = present[0]
        result, number = self.escalate(first, voice)
        self._skip(present[1:], voice, f"covered by the call placed for {first!r}", say=False)
        if result.pressed or result.uncertain:
            self.calls.append(self.clock())
            if number:
                self.phones.add(_digits(number))
        if getattr(result, "interrupted", False):
            self.interrupted = True
            raise KeyboardInterrupt
        if result.answered or result.uncertain:
            self._absorb_callee(before)

    def _skip(self, names: list, voice, why: str, say: bool = True) -> None:
        for n in names:
            if say:
                self.out(f"NOT CALLING for {n!r}: {why}")
            self.log_skip(n, voice, why)

    def _absorb_callee(self, before: Counter) -> None:
        """The engineer who joins because of our call must not be mistaken for the next visitor."""
        waited = 0.0
        while True:
            people = self._read()
            if people is not None:
                now = Counter(p.display_name for p in people if not p.is_me)
                arrived = [p for p in people if now[p.display_name] > before[p.display_name]
                           and self.kind(p) == "support"]
                if arrived:
                    self.out("engineer joined with a recognized phone number or trusted roster name: "
                             + ", ".join(repr(p.display_name) for p in arrived))
                    return
            if waited >= CALLEE_WAIT:
                self.out("no new participant appeared after the call. If the engineer shows up late, the "
                         "watcher may greet them as a visitor")
                return
            self.sleep(self.s.poll_seconds)
            waited += self.s.poll_seconds
