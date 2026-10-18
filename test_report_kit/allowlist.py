"""Known flaky tests that the ``flaky`` gate lets through for now. Every entry has an end date and a reason.

[[allow]]
test = "tests.test_net::test_retry_*"     # a name or a shell-style pattern
until = 2026-12-01                        # a TOML date: after this day the entry stops working
reason = "tracked in the team's tracker"
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import tomllib
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 1 << 20
KEYS = {"test", "until", "reason"}


class AllowlistError(Exception):
    pass


@dataclass
class Entry:
    test: str
    until: dt.date
    reason: str

    def matches(self, ident: str) -> bool:
        return fnmatch.fnmatchcase(ident, self.test)

    def expired(self, today: dt.date) -> bool:
        return today > self.until


def load(path: str | Path) -> list[Entry]:
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise AllowlistError(f"{path}: larger than {MAX_BYTES >> 10} KiB")
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AllowlistError(f"cannot read {path}: {exc.strerror}") from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise AllowlistError(f"{path}: not valid TOML: {exc}") from None
    unknown = set(doc) - {"allow"}
    if unknown:
        raise AllowlistError(
            f"{path}: unknown top-level key {sorted(unknown)[0]!r}, expected [[allow]] tables"
        )
    raw = doc.get("allow", [])
    if not isinstance(raw, list):
        raise AllowlistError(f"{path}: 'allow' must be an array of tables ([[allow]])")
    out = []
    for n, item in enumerate(raw, 1):
        where = f"{path}: entry {n}"
        if not isinstance(item, dict):
            raise AllowlistError(f"{where} is not a table")
        if set(item) - KEYS:
            raise AllowlistError(f"{where}: unknown key {sorted(set(item) - KEYS)[0]!r}")
        test, until, reason = item.get("test"), item.get("until"), item.get("reason")
        if not isinstance(test, str) or not test.strip():
            raise AllowlistError(f"{where}: 'test' must be a non-empty string")
        if isinstance(until, dt.datetime) or not isinstance(until, dt.date):
            raise AllowlistError(
                f"{where}: 'until' must be a date such as 2026-12-01 (an entry without an end date is refused)"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise AllowlistError(f"{where}: 'reason' must say why the test is allowed to be flaky")
        out.append(Entry(test, until, reason.strip()))
    return out
