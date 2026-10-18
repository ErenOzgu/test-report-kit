"""Markdown and self-contained HTML drawn from ``view.build``. Every value from a test report is escaped."""

from __future__ import annotations

import html
import json
import re
from typing import Any

LEGEND = "Per run, one character for each run in order: `.` passed, `F` failed, `E` error, `s` skipped, `r` passed after the test tool retried it, `-` not in that run."
SECTIONS = (
    ("failing", "Failing in every run"),
    ("flaky", "Flaky: passed and failed on the same code"),
)


# ---- markdown -----------------------------------------------------------------------------------------------


def code(value: object) -> str:
    """An inline code span that cannot be broken out of, whatever the text holds."""
    text = re.sub(r"[\r\n\t]+", " ", str(value)).replace("|", "\\|")
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def plain(value: object) -> str:
    return re.sub(r"([\\`*_{}\[\]<>()#+!|~&])", r"\\\1", re.sub(r"\s+", " ", str(value)))


def _pct(rate: float) -> str:
    return f"{rate * 100:.0f} %"


def _sigcell(sigs: list[dict[str, Any]], limit: int = 3) -> str:
    shown = ", ".join(code(s["id"]) for s in sigs[:limit])
    more = f" +{len(sigs) - limit}" if len(sigs) > limit else ""
    return (shown + more) or "–"


def _runs_line(v: dict[str, Any]) -> str:
    r = v["runs"]
    text = f"{r['count']} run{'s' if r['count'] != 1 else ''}"
    if r["commit_given"]:
        text += f" of {len(r['commits'])} commit{'s' if len(r['commits']) != 1 else ''}"
    t = v["totals"]
    return f"{text} · {t['tests']} test{'s' if t['tests'] != 1 else ''} · {t['failing']} failing · {t['flaky']} flaky · {t['skipped']} always skipped"


def markdown(v: dict[str, Any], summary: dict[str, Any] | None = None) -> str:
    out = [f"# {plain(v['title'])}", "", _runs_line(v), "", LEGEND, ""]
    if v["runs"]["duplicates"]:
        out += [
            f"_{v['runs']['duplicates']} test ids appeared more than once in a file; the worst result was kept._",
            "",
        ]
    multi = len(v["runs"]["commits"]) > 1
    for key, heading in SECTIONS:
        rows = v[key]
        out += [f"## {heading} ({len(rows)})", ""]
        if not rows:
            out += ["None.", ""]
            continue
        head = "| Test | " + ("Commit | " if multi else "") + "Per run | "
        sep = "|---|" + ("---|" if multi else "") + "---|"
        if key == "flaky":
            head += "Failed | Retried in-run | "
            sep += "---:|---:|"
        head += "Failure signatures |"
        sep += "---|"
        out += [head, sep]
        for r in rows:
            cells = [code(r["id"])]
            if multi:
                cells.append(code(r["commit"]))
            cells.append(code(r["pattern"]))
            if key == "flaky":
                cells += [_pct(r["fail_rate"]), str(r["retried"]) if r["retried"] else "–"]
            cells.append(_sigcell(r["signatures"]))
            out.append("| " + " | ".join(cells) + " |")
        out.append("")
    out += [f"## Failure signatures ({len(v['signatures'])})", ""]
    if v["signatures"]:
        out += ["| Id | Failures | Tests | Runs | Normalised message |", "|---|---:|---:|---:|---|"]
        for s in v["signatures"]:
            out.append(f"| {code(s['id'])} | {s['count']} | {s['tests']} | {s['runs']} | {code(s['text'])} |")
    else:
        out.append("None.")
    out.append("")
    out += [f"## Slowest tests (median seconds, top {len(v['slowest'])})", ""]
    if v["slowest"]:
        out += [
            "| Test | " + ("Commit | " if multi else "") + "Seconds |",
            "|---|" + ("---|" if multi else "") + "---:|",
        ]
        out += [
            f"| {code(s['id'])} | "
            + (f"{code(s['commit'])} | " if multi else "")
            + f"{s['median_seconds']:.3f} |"
            for s in v["slowest"]
        ]
    else:
        out.append("None.")
    out.append("")
    if v["absent"]:
        out += [f"## Not in every run ({len(v['absent'])})", "", "| Test | Missing from |", "|---|---:|"]
        out += [f"| {code(a['id'])} | {a['absent']} of {a['runs']} |" for a in v["absent"]]
        out.append("")
    if v["skipped"]:
        n = len(v["skipped"])
        out += [f"_{n} test{' was' if n == 1 else 's were'} skipped in every run._", ""]
    if summary is not None:
        out += summary_markdown(summary)
    return "\n".join(out).rstrip() + "\n"


def summary_markdown(s: dict[str, Any]) -> list[str]:
    out = [
        "## AI-written triage",
        "",
        f"> Written by {plain(s['model'])}. The signature ids it cites are checked against this report; "
        "its explanations are guesses.",
        "",
    ]
    if s.get("error"):
        return out + [f"Not available: {code(s['error'])}", ""]
    out += [plain(s["summary"]), ""]
    for c in s["clusters"]:
        out += [
            f"- {', '.join(code(i) for i in c['signatures'])}: {plain(c['likely_cause'])} "
            f"**Next:** {plain(c['next_step'])}"
        ]
    if s["clusters"]:
        out.append("")
    if s["dropped"]:
        out += [
            f"_{s['dropped']} cluster(s) the model wrote cited ids that are not in this report and were dropped._",
            "",
        ]
    return out


# ---- html ---------------------------------------------------------------------------------------------------

CSS = """
:root{--bg:#fff;--fg:#1f2328;--muted:#656d76;--line:#d0d7de;--card:#f6f8fa;--ok:#1a7f37;--bad:#cf222e;--warn:#9a6700;--accent:#0969da}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e;--line:#30363d;--card:#161b22;--ok:#3fb950;--bad:#f85149;--warn:#d29922;--accent:#58a6ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.6rem;margin:.2em 0}h2{font-size:1.15rem;margin:1.8em 0 .5em}
.sub{color:var(--muted)}.cards{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:120px}.card b{display:block;font-size:1.5rem}
.bad b{color:var(--bad)}.warn b{color:var(--warn)}.ok b{color:var(--ok)}
table{border-collapse:collapse;width:100%;display:block;overflow-x:auto}th,td{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}td.n{text-align:right}code,.pat{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-word}
.pat span{padding:0 1px}.pat .F,.pat .E{color:var(--bad);font-weight:700}.pat .p{color:var(--ok)}.pat .s,.pat .a{color:var(--muted)}
details{margin:6px 0}summary{cursor:pointer;color:var(--accent)}pre{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:10px;overflow-x:auto;white-space:pre-wrap;word-break:break-word}
.ai{border-left:4px solid var(--accent);padding:2px 14px;background:var(--card)}
"""

_PAT = {".": "p", "r": "p", "F": "F", "E": "E", "s": "s", "-": "a"}


def _e(x: object) -> str:
    return html.escape(str(x), quote=True)


def _pattern(p: str) -> str:
    return (
        '<span class="pat">'
        + "".join(f'<span class="{_PAT.get(c, "a")}">{_e(c)}</span>' for c in p)
        + "</span>"
    )


def _table(head: list[tuple[str, bool]], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{_e(h)}</th>" for h, _ in head)
    body = "".join(
        "<tr>"
        + "".join(f'<td class="n">{c}</td>' if head[i][1] else f"<td>{c}</td>" for i, c in enumerate(r))
        + "</tr>"
        for r in rows
    )
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def html_page(v: dict[str, Any], summary: dict[str, Any] | None = None) -> str:
    t = v["totals"]
    multi = len(v["runs"]["commits"]) > 1
    parts = [
        f"<h1>{_e(v['title'])}</h1>",
        f'<p class="sub">{_e(_runs_line(v))}</p>',
        f'<p class="sub">{_e(LEGEND.replace("`", ""))}</p>',
        '<div class="cards">'
        f'<div class="card bad"><b>{t["failing"]}</b>failing</div>'
        f'<div class="card warn"><b>{t["flaky"]}</b>flaky</div>'
        f'<div class="card ok"><b>{t["stable"]}</b>stable</div>'
        f'<div class="card"><b>{t["skipped"]}</b>always skipped</div></div>',
    ]
    for key, heading in SECTIONS:
        rows = v[key]
        parts.append(f"<h2>{_e(heading)} ({len(rows)})</h2>")
        if not rows:
            parts.append('<p class="sub">None.</p>')
            continue
        head = [("Test", False)] + ([("Commit", False)] if multi else []) + [("Per run", False)]
        if key == "flaky":
            head += [("Failed", True), ("Retried in-run", True)]
        head.append(("Failure signatures", False))
        body = []
        for r in rows:
            cells = [f"<code>{_e(r['id'])}</code>"]
            if multi:
                cells.append(f"<code>{_e(r['commit'])}</code>")
            cells.append(_pattern(r["pattern"]))
            if key == "flaky":
                cells += [_pct(r["fail_rate"]), str(r["retried"]) if r["retried"] else "–"]
            cells.append(", ".join(f"<code>{_e(s['id'])}</code>" for s in r["signatures"][:3]) or "–")
            body.append(cells)
        parts.append(_table(head, body))
    parts.append(f"<h2>Failure signatures ({len(v['signatures'])})</h2>")
    if v["signatures"]:
        parts.append(
            _table(
                [
                    ("Id", False),
                    ("Failures", True),
                    ("Tests", True),
                    ("Runs", True),
                    ("Normalised message", False),
                ],
                [
                    [
                        f"<code>{_e(s['id'])}</code>",
                        str(s["count"]),
                        str(s["tests"]),
                        str(s["runs"]),
                        f"<code>{_e(s['text'])}</code>"
                        + (
                            f"<details><summary>one failure in full</summary><pre>{_e(s['example'])}</pre></details>"
                            if s["example"]
                            else ""
                        ),
                    ]
                    for s in v["signatures"]
                ],
            )
        )
    else:
        parts.append('<p class="sub">None.</p>')
    parts.append(f"<h2>Slowest tests (median seconds, top {len(v['slowest'])})</h2>")
    if v["slowest"]:
        parts.append(
            _table(
                [("Test", False)] + ([("Commit", False)] if multi else []) + [("Seconds", True)],
                [
                    [f"<code>{_e(s['id'])}</code>"]
                    + ([f"<code>{_e(s['commit'])}</code>"] if multi else [])
                    + [f"{s['median_seconds']:.3f}"]
                    for s in v["slowest"]
                ],
            )
        )
    else:
        parts.append('<p class="sub">None.</p>')
    if v["absent"]:
        parts.append(f"<h2>Not in every run ({len(v['absent'])})</h2>")
        parts.append(
            _table(
                [("Test", False), ("Missing from", True)],
                [[f"<code>{_e(a['id'])}</code>", f"{a['absent']} of {a['runs']}"] for a in v["absent"]],
            )
        )
    if summary is not None:
        parts.append(_summary_html(summary))
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        f"<title>{_e(v['title'])}</title><style>{CSS}</style></head><body><main>{''.join(parts)}</main></body></html>\n"
    )


def _summary_html(s: dict[str, Any]) -> str:
    head = (
        '<h2>AI-written triage</h2><div class="ai"><p class="sub">'
        f"Written by {_e(s['model'])}. The signature ids it cites are checked against this report; its explanations are guesses.</p>"
    )
    if s.get("error"):
        return head + f"<p>Not available: {_e(s['error'])}</p></div>"
    items = "".join(
        f"<li>{', '.join(f'<code>{_e(i)}</code>' for i in c['signatures'])}: {_e(c['likely_cause'])} <b>Next:</b> {_e(c['next_step'])}</li>"
        for c in s["clusters"]
    )
    dropped = (
        f'<p class="sub">{s["dropped"]} cluster(s) cited ids that are not in this report and were dropped.</p>'
        if s["dropped"]
        else ""
    )
    return head + f"<p>{_e(s['summary'])}</p><ul>{items}</ul>{dropped}</div>"


def to_json(v: dict[str, Any], summary: dict[str, Any] | None = None) -> str:
    doc = dict(v)
    if summary is not None:
        doc["ai_summary"] = summary
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
