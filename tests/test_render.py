from __future__ import annotations

import json
import re
from html.parser import HTMLParser

import pytest

from test_report_kit import analyze, render, view
from test_report_kit.junit import parse_bytes

from .helpers import case, suite

HOSTILE_NAMES = [
    "a|b|c",
    "back`tick``s",
    "``` fence",
    "<script>alert(1)</script>",
    "[click](http://evil.example/x)",
    "line\nbreak",
    "*bold* _it_ # not a heading",
    "&amp; &lt; &#60;",
    "\"quote\" 'single'",
    "x" * 400,
    "ünïcödé ✓ 日本語",
    "![img](http://evil.example/a.png)",
]


def build(names=HOSTILE_NAMES, title="Report"):
    bodies = []
    for i in range(3):
        cs = [case(n, "fail" if i == 0 else "ok", msg=f"{n} failed {i}") for n in names]
        bodies.append(suite(*cs))
    runs = [parse_bytes(b, f"r{i}") for i, b in enumerate(bodies)]
    return view.build(analyze.analyze(runs), title)


def strip_code_spans(md: str) -> str:
    return re.sub(r"(?<!\\)(`+)(?!`)(.+?)(?<!`)\1(?!`)", "", md)


def table_rows(md: str):
    return [ln for ln in md.splitlines() if ln.startswith("|")]


def unescaped_pipes(row: str) -> int:
    return len(re.findall(r"(?<!\\)\|", row))


def test_hostile_test_names_cannot_break_a_markdown_table_or_inject_markup():
    md = render.markdown(build())
    rows = table_rows(md)
    assert rows
    # every row of a table has as many cells as its header: no name or message added a column
    tables, current = [], []
    for ln in md.splitlines():
        if ln.startswith("|"):
            current.append(ln)
        elif current:
            tables.append(current)
            current = []
    for t in tables:
        counts = {unescaped_pipes(r) for r in t}
        assert len(counts) == 1, t
    outside = strip_code_spans(md)
    assert "<script" not in outside and "](http" not in outside and "![" not in outside
    assert not re.search(r"(?<!\\)[<>]", outside), "an unescaped < or > outside a code span"


def test_the_title_is_escaped_too():
    md = render.markdown(build(["t"], title="<img src=x onerror=alert(1)> [x](http://e) # h"))
    first = md.splitlines()[0]
    assert (
        first.startswith("# ")
        and not re.search(r"(?<!\\)<img", first)
        and "\\<img" in first
        and "\\[x\\]" in first
    )


class Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[str] = []
        self.attrs: list[tuple[str, str, str | None]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs += [(tag, k, v) for k, v in attrs]

    def handle_data(self, data):
        self.text.append(data)


def test_the_html_is_one_file_with_no_script_no_event_handlers_and_nothing_loaded_from_elsewhere():
    page = render.html_page(build())
    p = Collect()
    p.feed(page)
    assert "script" not in p.tags and "img" not in p.tags and "a" not in p.tags and "iframe" not in p.tags
    assert not [a for a in p.attrs if a[1].startswith("on")]
    assert not [
        a for a in p.attrs if a[1] in ("src", "href") or (a[2] or "").startswith(("http:", "https:", "//"))
    ]
    csp = next(v for t, k, v in p.attrs if t == "meta" and k == "content" and v and "default-src" in v)
    assert "default-src 'none'" in csp and "script-src" not in csp
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "".join(p.text).count("ünïcödé ✓ 日本語") >= 1


def test_the_html_has_the_light_and_dark_theme_and_a_viewport():
    page = render.html_page(build(["t"]))
    assert "prefers-color-scheme:dark" in page and 'name="viewport"' in page and '<html lang="en">' in page


def test_the_json_is_stable_and_has_a_schema_number():
    v = build()
    a, b = render.to_json(v), render.to_json(build())
    assert a == b and a.endswith("\n")
    doc = json.loads(a)
    assert doc["schema"] == 1 and list(doc) == sorted(doc)
    assert set(doc) >= {
        "title",
        "runs",
        "totals",
        "failing",
        "flaky",
        "skipped",
        "signatures",
        "slowest",
        "absent",
    }


def test_the_summary_is_added_to_all_three_formats_and_labelled():
    s = {
        "model": "m<1>",
        "summary": "all <b>bad</b>",
        "clusters": [{"signatures": ["abcd1234"], "likely_cause": "x", "next_step": "y"}],
        "dropped": 1,
    }
    v = build(["t"])
    assert "AI-written triage" in render.markdown(v, s) and "guesses" in render.markdown(v, s)
    page = render.html_page(v, s)
    assert "AI-written triage" in page and "<b>bad</b>" not in page and "&lt;b&gt;bad&lt;/b&gt;" in page
    assert json.loads(render.to_json(v, s))["ai_summary"]["dropped"] == 1
    assert "ai_summary" not in json.loads(render.to_json(v))


def test_a_failed_summary_is_said_so_and_does_not_hide_the_report():
    s = {"model": "m", "error": "the API returned 401"}
    md = render.markdown(build(["t"]), s)
    assert "Not available: `the API returned 401`" in md and "## Failing in every run" in md


def test_no_runs_failing_gives_none_not_an_empty_table():
    runs = [parse_bytes(suite(case("t")), "r0"), parse_bytes(suite(case("t")), "r1")]
    md = render.markdown(view.build(analyze.analyze(runs)))
    assert (
        "## Failing in every run (0)\n\nNone." in md
        and "## Flaky: passed and failed on the same code (0)\n\nNone." in md
    )


def test_code_spans_survive_backticks_pipes_and_newlines():
    for text in ("plain", "a`b", "``", "`start", "end`", "a|b", "x\ny", "```a``b`"):
        out = render.code(text)
        assert "\n" not in out
        m = re.fullmatch(r"(`+) ?(.*?) ?\1", out)
        assert m, out
        # the fence is longer than any run of backticks inside
        inner_runs = [len(r) for r in re.findall(r"`+", text)]
        assert len(m.group(1)) > max(inner_runs, default=0)


@pytest.mark.parametrize("n", [0, 1, 5])
def test_top_limits_the_slowest_list(n):
    v = view.build(analyze.analyze([parse_bytes(suite(*(case(f"t{i}", t=i) for i in range(8))), "r")]), top=n)
    assert len(v["slowest"]) == n


def test_the_commit_is_only_mentioned_when_the_files_gave_one():
    plain = view.build(
        analyze.analyze([parse_bytes(suite(case("t")), "a"), parse_bytes(suite(case("t")), "b")])
    )
    assert plain["runs"]["commit_given"] is False and " commit" not in render.markdown(plain).splitlines()[2]
    given = view.build(analyze.analyze([parse_bytes(suite(case("t"), commit="c1"), "a")]))
    assert given["runs"]["commit_given"] is True and "of 1 commit" in render.markdown(given).splitlines()[2]
