"""Reading JUnit XML, whatever tool wrote it.

pytest, Maven Surefire and Failsafe, Gradle, jest-junit, go-junit-report, phpunit, RSpec and most others write
the same few elements, with small differences. What is read here: ``testsuite`` (anywhere, nested or inside
``testsuites``), ``testcase`` with ``classname``, ``name`` and ``time``, and inside a test case ``failure``,
``error``, ``skipped``, plus Surefire's ``flakyFailure``, ``flakyError``, ``rerunFailure`` and ``rerunError``
(a test that failed and then passed on a retry inside one run).

The file is untrusted input. It is refused if it has a DOCTYPE or declares entities (billion-laughs and external-entity tricks
both need one, and JUnit output never has one), if it is larger than ``MAX_BYTES``, or if it has more than ``MAX_CASES`` test cases.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024
MAX_CASES = 200_000
MAX_TEXT = 4000  # characters kept of a failure message or its details

PASSED, FAILED, ERROR, SKIPPED = "passed", "failed", "error", "skipped"
BAD = (FAILED, ERROR)

_ENTITY = re.compile(rb"<!ENTITY|<!DOCTYPE", re.IGNORECASE)
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_RAW_BAD = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_CHARREF = re.compile(rb"&#(?:[xX]([0-9a-fA-F]{1,8})|([0-9]{1,10}));")


class JUnitError(Exception):
    """The file cannot be read as JUnit XML. The message says which file and why."""


@dataclass
class Case:
    id: str  # "classname::name", or just the name when there is no class
    classname: str
    name: str
    status: str
    seconds: float = 0.0
    message: str = ""
    details: str = ""
    retries: list[str] = field(
        default_factory=list
    )  # messages of attempts the tool itself retried (Surefire)
    suite: str = ""

    @property
    def retried(self) -> int:
        return len(self.retries)


@dataclass
class Run:
    label: str
    source: str
    cases: dict[str, Case] = field(default_factory=dict)
    commit: str | None = None
    duplicates: int = 0  # test ids that appeared more than once in the file (the last one is kept)
    timestamp: str | None = None

    @property
    def counts(self) -> dict[str, int]:
        out = {PASSED: 0, FAILED: 0, ERROR: 0, SKIPPED: 0}
        for c in self.cases.values():
            out[c.status] += 1
        return out


def clean(text: str | None, limit: int = MAX_TEXT) -> str:
    text = _CONTROL.sub("", text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _seconds(value: str | None) -> float:
    try:
        x = float((value or "0").replace(",", "."))
    except ValueError:
        return 0.0
    return x if 0 <= x < 1e7 else 0.0  # also rejects nan and inf


def _legal(code: int) -> bool:
    return (
        code in (0x9, 0xA, 0xD)
        or 0x20 <= code <= 0xD7FF
        or 0xE000 <= code <= 0xFFFD
        or 0x10000 <= code <= 0x10FFFF
    )


def _repair(data: bytes) -> bytes:
    """Test tools often copy terminal output, escape codes included, into the report. XML 1.0 forbids those
    characters, raw or as numeric references, so a strict parser rejects the whole file. They become spaces."""

    def ref(m: re.Match[bytes]) -> bytes:
        code = int(m.group(1), 16) if m.group(1) else int(m.group(2))
        return m.group(0) if _legal(code) else b" "

    return _CHARREF.sub(ref, _RAW_BAD.sub(b" ", data))


def parse_bytes(data: bytes, label: str, source: str = "") -> Run:
    if len(data) > MAX_BYTES:
        raise JUnitError(f"{source or label}: larger than {MAX_BYTES >> 20} MiB")
    if b"\x00" in data[:200]:
        raise JUnitError(f"{source or label}: UTF-16 and UTF-32 are not supported, write the report as UTF-8")
    if _ENTITY.search(data):
        raise JUnitError(
            f"{source or label}: refused, it has a DOCTYPE or declares XML entities (JUnit output has neither)"
        )
    try:
        root = ET.fromstring(_repair(data))
    except (ET.ParseError, LookupError, ValueError, RecursionError) as exc:  # LookupError: encoding="UTr-8"
        raise JUnitError(f"{source or label}: not valid XML: {exc}") from None
    if _local(root.tag) not in ("testsuites", "testsuite"):
        raise JUnitError(
            f"{source or label}: the root element is <{_local(root.tag)}>, expected <testsuites> or <testsuite>"
        )
    run = Run(label, source or label)
    for prop in root.iter():
        if _local(prop.tag) == "property" and prop.get("name") in ("commit", "git.commit", "sha", "git_sha"):
            run.commit = clean(prop.get("value"), 64) or None
        if _local(prop.tag) == "testsuite" and run.timestamp is None and prop.get("timestamp"):
            run.timestamp = clean(prop.get("timestamp"), 40)
    for suite in root.iter():
        if _local(suite.tag) != "testsuite":
            continue
        for case in suite:
            if _local(case.tag) != "testcase":
                continue
            if len(run.cases) >= MAX_CASES:
                raise JUnitError(f"{source or label}: more than {MAX_CASES} test cases")
            _add(run, suite.get("name", ""), case)
    return run


def _add(run: Run, suite_name: str, case: ET.Element) -> None:
    name = clean(case.get("name"), 300) or "(unnamed)"
    classname = clean(case.get("classname"), 300)
    ident = f"{classname}::{name}" if classname else name
    status, message, details, retries = PASSED, "", "", []
    for child in case:
        kind = _local(child.tag).lower()
        if kind in ("failure", "error") and status not in BAD:
            status = FAILED if kind == "failure" else ERROR
            message = clean(child.get("message") or child.get("type") or "", 1000)
            details = clean(child.text)
        elif kind == "skipped" and status == PASSED:
            status = SKIPPED
            message = clean(child.get("message"), 1000)
        elif kind in ("flakyfailure", "flakyerror", "rerunfailure", "rerunerror"):
            retries.append(clean(child.get("message") or child.get("type") or kind, 1000))
    if status in BAD and not message:
        message = details.splitlines()[0][:300] if details else status
    c = Case(
        ident,
        classname,
        name,
        status,
        _seconds(case.get("time")),
        message,
        details,
        retries,
        clean(suite_name, 200),
    )
    if ident in run.cases:
        run.duplicates += 1
    run.cases[ident] = c


def read(path: str | Path, label: str | None = None) -> Run:
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise JUnitError(f"{path}: larger than {MAX_BYTES >> 20} MiB")
        data = path.read_bytes()
    except OSError as exc:
        raise JUnitError(f"cannot read {path}: {exc.strerror}") from None
    return parse_bytes(data, label or path.stem, str(path))


MAX_FILES = 5000
MAX_TOTAL_CASES = 2_000_000


def merge(label: str, parts: list[Run]) -> Run:
    """Several files of one run (shards, one file per module) become one run.

    A test that is in more than one file keeps its worst result. Files with different commits are refused,
    because they cannot be the same run.
    """
    if len(parts) == 1:
        only = parts[0]
        only.label = label
        return only
    commits = {p.commit for p in parts if p.commit}
    if len(commits) > 1:
        raise JUnitError(f"{label}: the files in it are for different commits: {', '.join(sorted(commits))}")
    out = Run(
        label,
        label,
        commit=next(iter(commits), None),
        timestamp=next((p.timestamp for p in parts if p.timestamp), None),
    )
    for part in parts:
        out.duplicates += part.duplicates
        for ident, case in part.cases.items():
            old = out.cases.get(ident)
            if old is None:
                out.cases[ident] = case
                continue
            out.duplicates += 1
            if (case.status in BAD and old.status not in BAD) or (
                case.status == PASSED and old.status == SKIPPED
            ):
                out.cases[ident] = case
    return out


def _xml_files(directory: Path) -> list[Path]:
    found: list[Path] = []
    for root, dirs, files in _walk(directory):
        dirs.sort()
        for name in sorted(files):
            p = Path(root) / name
            if name.lower().endswith(".xml") and not p.is_symlink():
                found.append(p)
                if len(found) > MAX_FILES:
                    raise JUnitError(f"{directory}: more than {MAX_FILES} XML files")
    return found


def _walk(directory: Path):  # Path.walk needs Python 3.12
    for root, dirs, files in os.walk(directory):
        yield Path(root), dirs, files


def load(paths: list[str]) -> list[Run]:
    """One run per argument: a file is a run, a directory is a run made of all the XML files below it."""
    runs: list[Run] = []
    seen: set[str] = set()
    total = 0
    for arg in paths:
        p = Path(arg)
        if p.is_dir():
            files = _xml_files(p)
            if not files:
                raise JUnitError(f"{arg}: no .xml files in it")
            run = merge(p.name or str(p), [read(f) for f in files])
        else:
            run = read(p)
        label, n = run.label, 2
        while label in seen:
            label, n = f"{run.label}#{n}", n + 1
        run.label = label
        seen.add(label)
        total += len(run.cases)
        if total > MAX_TOTAL_CASES:
            raise JUnitError(f"more than {MAX_TOTAL_CASES} test cases in all")
        runs.append(run)
    if not runs:
        raise JUnitError("no test reports given")
    return runs
