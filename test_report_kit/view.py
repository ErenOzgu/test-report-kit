"""The numbers a report shows, as plain data. Markdown, HTML and JSON are all drawn from this one dictionary."""

from __future__ import annotations

from typing import Any

from .analyze import FAILING, FLAKY, SKIPPED_ALL, STABLE, UNSPECIFIED, Analysis, TestResult

SCHEMA = 1
EXAMPLE_CHARS = 1000


def _sigs(t: TestResult) -> list[dict[str, Any]]:
    return [{"id": i, "count": n} for i, n in sorted(t.signatures.items(), key=lambda kv: (-kv[1], kv[0]))]


def _row(t: TestResult, commit: str) -> dict[str, Any]:
    return {
        "id": t.id,
        "commit": commit,
        "verdict": t.verdict,
        "pattern": t.pattern,
        "passes": t.passes,
        "fails": t.fails,
        "retried": t.retried,
        "fail_rate": round(t.fail_rate, 3),
        "median_seconds": round(t.median_seconds, 3),
        "signatures": _sigs(t),
    }


def build(analysis: Analysis, title: str = "Test report", top: int = 10) -> dict[str, Any]:
    rows = [(g.commit, t) for g in analysis.groups for t in g.tests]
    by = {v: [_row(t, c) for c, t in rows if t.verdict == v] for v in (FAILING, FLAKY, SKIPPED_ALL, STABLE)}
    slowest = sorted(
        ((t.median_seconds, c, t) for c, t in rows if t.seconds), key=lambda x: (-x[0], x[1], x[2].id)
    )[:top]
    absent = [
        {"id": t.id, "commit": c, "absent": t.absent, "runs": len(g.runs)}
        for g in analysis.groups
        for c, t in ((g.commit, t) for t in g.tests)
        if t.absent
    ]
    signatures = sorted(analysis.signatures.values(), key=lambda s: (-s.count, s.id))
    commits = [g.commit for g in analysis.groups]
    return {
        "schema": SCHEMA,
        "title": title,
        "runs": {
            "count": analysis.run_count,
            "labels": [r.label for r in analysis.runs],
            "commits": commits,
            "commit_given": commits != [UNSPECIFIED],
            "duplicates": sum(r.duplicates for r in analysis.runs),
        },
        "totals": {
            "tests": len(rows),
            **{v: len(by[v]) for v in (FAILING, FLAKY, SKIPPED_ALL, STABLE)},
        },
        "failing": by[FAILING],
        "flaky": by[FLAKY],
        "skipped": by[SKIPPED_ALL],
        "signatures": [
            {
                "id": s.id,
                "text": s.text,
                "count": s.count,
                "tests": len(s.tests),
                "runs": len(s.runs),
                "example": s.example[:EXAMPLE_CHARS],
            }
            for s in signatures
        ],
        "slowest": [{"id": t.id, "commit": c, "median_seconds": round(m, 3)} for m, c, t in slowest],
        "absent": absent,
    }
