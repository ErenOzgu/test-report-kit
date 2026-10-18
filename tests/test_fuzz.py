"""Whatever is in a report file, the kit either reads it or says why not. It never crashes and never invents."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from test_report_kit import analyze, render, view
from test_report_kit.junit import JUnitError, parse_bytes

ROOT = Path(__file__).resolve().parent.parent
SEEDS = [p.read_bytes() for p in sorted((ROOT / "examples" / "runs").rglob("*.xml"))]
assert len(SEEDS) >= 9


def mutate(data: bytes, rnd: random.Random) -> bytes:
    b = bytearray(data)
    for _ in range(rnd.randint(1, 12)):
        kind = rnd.randrange(6)
        if not b:
            break
        i = rnd.randrange(len(b))
        if kind == 0:
            b[i] = rnd.randrange(256)
        elif kind == 1:
            del b[i : i + rnd.randint(1, 40)]
        elif kind == 2:
            b[i:i] = rnd.choice(
                [b"<", b">", b"&", b'"', b"&#0;", b"&#x1B;", b"<![CDATA[", b"]]>", b"\x00", b"\xff\xfe"]
            )
        elif kind == 3:
            j = rnd.randrange(len(b))
            b[i:i] = b[j : j + rnd.randint(1, 200)]
        elif kind == 4:
            b = b[:i]
        else:
            b[i:i] = rnd.choice(
                [b"<testcase", b"</testsuite>", b"<failure", b"<skipped/>", b'time="nan"', b"<properties>"]
            )
    return bytes(b)


def check_everything(data: bytes) -> None:
    try:
        run = parse_bytes(data, "fuzz")
    except JUnitError:
        return
    a = analyze.analyze([run, run])
    v = view.build(a)
    md = render.markdown(v)
    page = render.html_page(v)
    render.to_json(v)
    assert "<script" not in page.lower() and "<script" not in md.lower().replace("\\<script", "")
    t = v["totals"]
    assert t["tests"] == t["failing"] + t["flaky"] + t["skipped"] + t["stable"] == len(run.cases)


@pytest.mark.parametrize("n", range(len(SEEDS)))
def test_mutated_example_files_are_read_or_refused_cleanly(n):
    rnd = random.Random(1000 + n)
    for _ in range(150):
        check_everything(mutate(SEEDS[n], rnd))


def test_random_bytes_and_random_unicode_names():
    rnd = random.Random(7)
    for _ in range(300):
        check_everything(bytes(rnd.randrange(256) for _ in range(rnd.randint(0, 300))))
    alphabet = [
        "<",
        ">",
        "&",
        "|",
        "`",
        "\n",
        "\t",
        "\\",
        "'",
        '"',
        "é",
        "日",
        "‮",
        "\u0000",
        "\ud800",
        "[",
        "]",
        "(",
        ")",
        "*",
        "_",
        "#",
    ]
    for _ in range(200):
        name = "".join(rnd.choice(alphabet + list("abc012 ")) for _ in range(rnd.randint(0, 40)))
        from xml.sax.saxutils import quoteattr

        try:
            data = f"<testsuite><testcase classname={quoteattr(name)} name={quoteattr(name[::-1])}><failure message={quoteattr(name)}/></testcase></testsuite>".encode(
                "utf-8", "replace"
            )
        except Exception:  # noqa: BLE001
            continue
        check_everything(data)


def test_the_analysis_properties_hold_for_random_suites():
    rnd = random.Random(99)
    from .helpers import case, suite

    for _ in range(60):
        n_tests, n_runs = rnd.randint(1, 8), rnd.randint(1, 7)
        bodies = []
        for _r in range(n_runs):
            cs = [
                case(
                    f"t{t}",
                    rnd.choice(["ok", "ok", "fail", "err", "skip"]),
                    msg=f"m{rnd.randint(0, 3)} {rnd.randint(0, 99)}",
                )
                for t in range(n_tests)
                if rnd.random() > 0.1
            ]
            bodies.append(suite(*cs, commit=rnd.choice([None, "a", "b"])))
        runs = [parse_bytes(b, f"r{i}") for i, b in enumerate(bodies)]
        a = analyze.analyze(runs)
        for g in a.groups:
            for t in g.tests:
                assert len(t.marks) == len(g.runs) == len(t.outcomes)
                assert t.passes + t.fails + t.skips + t.absent == len(g.runs)
                bad = t.fails > 0
                assert (t.verdict == "failing") == (bad and t.passes == 0)
                assert (t.verdict == "flaky") == (bad and t.passes > 0)
                assert sum(t.signatures.values()) == t.fails
        assert sum(s.count for s in a.signatures.values()) == sum(t.fails for t in a.tests)
