"""``test-report-kit``: report, flaky (a gate) and compare."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

from . import __version__, allowlist, junit, render, summary, view
from .analyze import FAILING, FLAKY, Analysis, analyze, compare

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2

DESCRIPTION = (
    "Read JUnit XML from several runs of the same tests, find the flaky ones, group the failures and write a "
    "report. A file is one run; a directory is one run made of all the .xml files below it."
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="test-report-kit", description=DESCRIPTION)
    p.add_argument("--version", action="version", version=f"test-report-kit {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="{report,flaky,compare}")

    r = sub.add_parser("report", help="write a Markdown, HTML or JSON report of the runs")
    r.add_argument("paths", nargs="+", metavar="PATH", help="JUnit XML files or directories, one run each")
    r.add_argument(
        "--format", choices=("md", "html", "json"), default="md", help="output format (default: md)"
    )
    r.add_argument("-o", "--output", metavar="FILE", help="write here instead of standard output")
    r.add_argument("--title", default="Test report", help="the title of the report")
    r.add_argument(
        "--top", type=int, default=10, metavar="N", help="how many slowest tests to list (default: 10)"
    )
    r.add_argument(
        "--summarize", action="store_true", help="add a model-written triage (needs ANTHROPIC_API_KEY)"
    )
    r.add_argument("--model", default=summary.DEFAULT_MODEL, metavar="MODEL", help="model for --summarize")

    f = sub.add_parser("flaky", help="exit 1 if any test is flaky (a CI gate)")
    f.add_argument("paths", nargs="+", metavar="PATH", help="JUnit XML files or directories, one run each")
    f.add_argument(
        "--allowlist", metavar="FILE", help="TOML file of known flaky tests; every entry has an end date"
    )
    f.add_argument(
        "--fail-on",
        choices=("flaky", "failing", "both"),
        default="flaky",
        help="what fails the gate (default: flaky)",
    )
    f.add_argument(
        "--min-runs", type=int, default=2, metavar="N", help="runs of one commit needed to judge (default: 2)"
    )
    f.add_argument(
        "--strict-allowlist", action="store_true", help="also fail on entries that match no flaky test"
    )
    f.add_argument(
        "--today", metavar="YYYY-MM-DD", help="the date to check end dates against (default: today)"
    )
    f.add_argument("--format", choices=("text", "json"), default="text", help="output format (default: text)")

    c = sub.add_parser("compare", help="what changed between two sets of runs")
    c.add_argument("--before", nargs="+", required=True, metavar="PATH", help="runs of the earlier code")
    c.add_argument("--after", nargs="+", required=True, metavar="PATH", help="runs of the later code")
    c.add_argument("--format", choices=("md", "json"), default="md", help="output format (default: md)")
    c.add_argument("-o", "--output", metavar="FILE", help="write here instead of standard output")
    c.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="exit 1 if a test that did not fail now fails every time",
    )
    return p


def _err(msg: str) -> int:
    print(f"test-report-kit: {msg}", file=sys.stderr)
    return EXIT_USAGE


def _write(text: str, output: str | None, inputs: list[str]) -> None:
    if output is None or output == "-":
        sys.stdout.write(text)
        return
    target = Path(output)
    for i in inputs:
        if Path(i).exists() and target.exists() and os.path.samefile(i, target):
            raise OSError("the output file is one of the inputs")
    if target.exists() and not target.is_file():
        raise OSError(f"{output} exists and is not a regular file")
    fd, tmp = tempfile.mkstemp(dir=target.parent or ".", prefix=".trk-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _load(paths: list[str]) -> Analysis:
    return analyze(junit.load(paths))


def cmd_report(a: argparse.Namespace) -> int:
    if a.top < 0 or a.top > 1000:
        return _err("--top must be between 0 and 1000")
    analysis = _load(a.paths)
    v = view.build(analysis, a.title, a.top)
    ai = None
    if a.summarize:
        try:
            ai = summary.summarize(v, a.model)
        except summary.SummaryError as exc:
            print(f"test-report-kit: the AI summary was skipped: {exc}", file=sys.stderr)
            ai = {"model": a.model, "error": str(exc)}
    if a.format == "json":
        text = render.to_json(v, ai)
    elif a.format == "html":
        text = render.html_page(v, ai)
    else:
        text = render.markdown(v, ai)
    _write(text, a.output, a.paths)
    return EXIT_OK


def _gate(analysis: Analysis, a: argparse.Namespace, today: dt.date) -> tuple[int, dict]:
    entries = allowlist.load(a.allowlist) if a.allowlist else []
    for g in analysis.groups:
        if len(g.runs) < a.min_runs:
            raise junit.JUnitError(
                f"only {len(g.runs)} run(s) of commit {g.commit}: at least {a.min_runs} runs of the same code are "
                "needed to tell a flaky test from a failing one (see --min-runs)"
            )
    wanted = {"flaky": (FLAKY,), "failing": (FAILING,), "both": (FLAKY, FAILING)}[a.fail_on]
    blocked, allowed, expired, used = [], [], [], set()
    for t in analysis.tests:
        if t.verdict not in wanted:
            continue
        hit = next((e for e in entries if e.matches(t.id)), None)
        if hit is None:
            blocked.append(t)
        elif hit.expired(today):
            expired.append((t, hit))
            blocked.append(t)
            used.add(id(hit))
        else:
            allowed.append((t, hit))
            used.add(id(hit))
    unused = [e for e in entries if id(e) not in used]
    failed = bool(blocked) or (a.strict_allowlist and bool(unused))
    doc = {
        "blocked": [{"id": t.id, "verdict": t.verdict, "pattern": t.pattern} for t in blocked],
        "allowed": [
            {"id": t.id, "pattern": t.pattern, "until": e.until.isoformat(), "reason": e.reason}
            for t, e in allowed
        ],
        "expired": [{"id": t.id, "until": e.until.isoformat(), "reason": e.reason} for t, e in expired],
        "unused_allowlist": [{"test": e.test, "until": e.until.isoformat()} for e in unused],
        "runs": analysis.run_count,
    }
    return (EXIT_FAIL if failed else EXIT_OK), doc


def cmd_flaky(a: argparse.Namespace) -> int:
    if a.min_runs < 1:
        return _err("--min-runs must be at least 1")
    try:
        today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    except ValueError:
        return _err("--today must be a date like 2026-12-01")
    analysis = _load(a.paths)
    code, doc = _gate(analysis, a, today)
    if a.format == "json":
        sys.stdout.write(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        return code
    expired_ids = {e["id"] for e in doc["expired"]}
    for t in analysis.tests:
        if t.id in expired_ids:
            continue
        if any(b["id"] == t.id for b in doc["blocked"]):
            sigs = ", ".join(sorted(t.signatures)) or "-"
            print(f"{t.verdict.upper():8} {t.id}  {t.pattern}  signatures: {sigs}")
    for e in doc["expired"]:
        print(f"EXPIRED  {e['id']}  allowed until {e['until']} ({e['reason']})")
    for e in doc["allowed"]:
        print(f"allowed  {e['id']}  {e['pattern']}  until {e['until']} ({e['reason']})")
    for e in doc["unused_allowlist"]:
        print(
            f"unused   allowlist entry {e['test']!r} (until {e['until']}) matches no {a.fail_on} test; remove it"
        )
    n = len(doc["blocked"])
    print(
        f"{n} test(s) block the gate across {doc['runs']} runs."
        if code
        else f"ok: no blocking tests across {doc['runs']} runs."
    )
    return code


def cmd_compare(a: argparse.Namespace) -> int:
    before, after = _load(a.before), _load(a.after)
    cmp = compare(before, after)
    if a.format == "json":
        doc = {
            "schema": view.SCHEMA,
            "newly_failing": [c.id for c in cmp.newly_failing],
            "fixed": [c.id for c in cmp.fixed],
            "newly_flaky": [c.id for c in cmp.newly_flaky],
            "new_tests": cmp.new_tests,
            "removed_tests": cmp.removed_tests,
            "slower": [{"id": i, "before": round(x, 3), "after": round(y, 3)} for i, x, y in cmp.slower],
        }
        text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    else:
        text = _compare_md(cmp)
    _write(text, a.output, a.before + a.after)
    return EXIT_FAIL if a.fail_on_regression and cmp.newly_failing else EXIT_OK


def _compare_md(cmp) -> str:  # noqa: ANN001
    out = ["# Changes between two sets of runs", ""]
    sections = [
        ("Newly failing", [(c.id, f"was {c.before}") for c in cmp.newly_failing]),
        ("Fixed", [(c.id, f"now {c.after}") for c in cmp.fixed]),
        ("Newly flaky", [(c.id, "was stable") for c in cmp.newly_flaky]),
        ("New tests", [(i, "") for i in cmp.new_tests]),
        ("Removed tests", [(i, "") for i in cmp.removed_tests]),
        (
            "Slower (median at least twice as long)",
            [(i, f"{x:.3f} s to {y:.3f} s") for i, x, y in cmp.slower],
        ),
    ]
    for title, rows in sections:
        out += [f"## {title} ({len(rows)})", ""]
        out += [f"- {render.code(i)} {render.plain(note)}".rstrip() for i, note in rows] or ["None."]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {"report": cmd_report, "flaky": cmd_flaky, "compare": cmd_compare}[args.command](args)
    except (junit.JUnitError, allowlist.AllowlistError) as exc:
        return _err(str(exc))
    except OSError as exc:
        return _err(f"{exc.strerror or exc}")
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
