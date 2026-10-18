"""What the runs say: which tests are stable, which are flaky, which always fail, and why they fail.

Runs are repeated runs of the same code. A test that both passed and failed in them is **flaky**; one that never
passed is **failing**. If the runs carry a commit (a ``commit`` property in the XML), runs are only compared with
runs of the same commit, so a test that was fixed between two commits is not called flaky.
"""

from __future__ import annotations

import hashlib
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .junit import BAD, ERROR, FAILED, PASSED, SKIPPED, Case, Run

SYMBOL = {PASSED: ".", FAILED: "F", ERROR: "E", SKIPPED: "s", None: "-"}
RETRIED_PASS = "r"
UNSPECIFIED = "(no commit given)"

STABLE, FLAKY, FAILING, SKIPPED_ALL = "stable", "flaky", "failing", "skipped"
VERDICT_ORDER = (FAILING, FLAKY, SKIPPED_ALL, STABLE)

_NUMBER = re.compile(r"(?<![A-Za-z_\d])-?\d+(?:\.\d+)?")
_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b|\b(?=[0-9]*[a-fA-F])[0-9a-fA-F]{12,}\b")
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_TIME = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b")
_PATH = re.compile(r"(?:(?<=\s)|^|(?<=[\"'(=]))(?:/[\w.@+~-]+){2,}/?|[A-Za-z]:\\(?:[\w .-]+\\)+[\w .-]*")
_SPACE = re.compile(r"\s+")


def signature_text(message: str) -> str:
    """A failure message with the parts that change from run to run replaced, so equal failures group together."""
    first = next((ln for ln in message.splitlines() if ln.strip()), "")[:300]
    text = _TIME.sub("<time>", first)
    text = _UUID.sub("<uuid>", text)
    text = _HEX.sub("<hex>", text)
    text = _PATH.sub("<path>", text)
    text = _NUMBER.sub("N", text)
    return _SPACE.sub(" ", text).strip() or "(no message)"


def signature_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


@dataclass
class TestResult:
    id: str
    name: str
    classname: str
    outcomes: list[str | None]  # one per run of the group, in order
    marks: list[str]  # the same as one character each
    seconds: list[float]
    verdict: str
    passes: int
    fails: int
    skips: int
    absent: int
    retried: int  # failed attempts retried and passed inside a single run
    signatures: Counter = field(default_factory=Counter)

    @property
    def pattern(self) -> str:
        return "".join(self.marks)

    @property
    def fail_rate(self) -> float:
        done = self.passes + self.fails + self.retried
        return (self.fails + self.retried) / done if done else 0.0

    @property
    def median_seconds(self) -> float:
        return statistics.median(self.seconds) if self.seconds else 0.0


@dataclass
class Signature:
    id: str
    text: str
    count: int = 0  # failures
    tests: set[str] = field(default_factory=set)
    runs: set[str] = field(default_factory=set)
    example: str = ""  # the detail text of one failure


@dataclass
class Group:
    commit: str
    runs: list[Run]
    tests: list[TestResult]

    def of(self, verdict: str) -> list[TestResult]:
        return [t for t in self.tests if t.verdict == verdict]


@dataclass
class Analysis:
    groups: list[Group]
    signatures: dict[str, Signature]
    runs: list[Run]

    @property
    def tests(self) -> list[TestResult]:
        return [t for g in self.groups for t in g.tests]

    def of(self, verdict: str) -> list[TestResult]:
        return [t for t in self.tests if t.verdict == verdict]

    @property
    def run_count(self) -> int:
        return len(self.runs)


def analyze(runs: list[Run]) -> Analysis:
    by_commit: dict[str, list[Run]] = defaultdict(list)
    for r in runs:
        by_commit[r.commit or UNSPECIFIED].append(r)
    signatures: dict[str, Signature] = {}
    groups = []
    for commit, rs in by_commit.items():
        ids = sorted({i for r in rs for i in r.cases})
        tests = [_result(i, rs, signatures) for i in ids]
        tests.sort(key=lambda t: (VERDICT_ORDER.index(t.verdict), -t.fail_rate, t.id))
        groups.append(Group(commit, rs, tests))
    return Analysis(groups, signatures, runs)


def _result(ident: str, runs: list[Run], signatures: dict[str, Signature]) -> TestResult:
    cases: list[Case | None] = [r.cases.get(ident) for r in runs]
    seen = [c for c in cases if c is not None]
    outcomes = [c.status if c else None for c in cases]
    passes = sum(1 for c in seen if c.status == PASSED)
    fails = sum(1 for c in seen if c.status in BAD)
    skips = sum(1 for c in seen if c.status == SKIPPED)
    retried = sum(c.retried for c in seen if c.status == PASSED)
    sigs: Counter = Counter()
    marks = []
    for run, c in zip(runs, cases, strict=True):
        marks.append(SYMBOL[c.status if c else None])
        if c is None:
            continue
        seen_messages = [(c.message, c.details or c.message)] if c.status in BAD else []
        if c.status == PASSED:  # failed attempts the test tool retried: still evidence of the failure
            seen_messages = [(m, m) for m in c.retries]
            if c.retries:
                marks[-1] = RETRIED_PASS
        for message, example in seen_messages:
            text = signature_text(message)
            sid = signature_id(text)
            sig = signatures.setdefault(sid, Signature(sid, text, example=example))
            sig.count += 1
            sig.tests.add(ident)
            sig.runs.add(run.label)
            sigs[sid] += 1
    if fails and passes:
        verdict = FLAKY
    elif fails:
        verdict = FAILING
    elif passes and retried:
        verdict = FLAKY  # failed, was retried by the test tool and passed: the same evidence from one run
    elif passes:
        verdict = STABLE
    else:
        verdict = SKIPPED_ALL
    first = seen[0]
    return TestResult(
        ident,
        first.name,
        first.classname,
        outcomes,
        marks,
        [c.seconds for c in seen],
        verdict,
        passes,
        fails,
        skips,
        len(cases) - len(seen),
        retried,
        sigs,
    )


# ---- two sets of runs compared --------------------------------------------------------------------------------


@dataclass
class Change:
    id: str
    before: str
    after: str


@dataclass
class Comparison:
    newly_failing: list[Change]
    fixed: list[Change]
    new_tests: list[str]
    removed_tests: list[str]
    newly_flaky: list[Change]
    slower: list[tuple[str, float, float]]  # id, before seconds, after seconds


def _verdicts(a: Analysis) -> dict[str, TestResult]:
    out: dict[str, TestResult] = {}
    for t in a.tests:
        old = out.get(t.id)
        if old is None or VERDICT_ORDER.index(t.verdict) < VERDICT_ORDER.index(old.verdict):
            out[t.id] = t
    return out


def compare(
    before: Analysis, after: Analysis, slower_factor: float = 2.0, slower_min: float = 0.5
) -> Comparison:
    b, a = _verdicts(before), _verdicts(after)
    newly_failing, fixed, newly_flaky, slower = [], [], [], []
    for i in sorted(set(a) & set(b)):
        x, y = b[i], a[i]
        if y.verdict == FAILING and x.verdict != FAILING:
            newly_failing.append(Change(i, x.verdict, y.verdict))
        elif x.verdict == FAILING and y.verdict in (STABLE, FLAKY):
            fixed.append(Change(i, x.verdict, y.verdict))
        elif y.verdict == FLAKY and x.verdict == STABLE:
            newly_flaky.append(Change(i, x.verdict, y.verdict))
        if y.median_seconds >= slower_min and y.median_seconds >= slower_factor * max(
            x.median_seconds, 0.001
        ):
            slower.append((i, x.median_seconds, y.median_seconds))
    return Comparison(
        newly_failing, fixed, sorted(set(a) - set(b)), sorted(set(b) - set(a)), newly_flaky, slower
    )
