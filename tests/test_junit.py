from __future__ import annotations

import os

import pytest

from test_report_kit import junit
from test_report_kit.junit import JUnitError, parse_bytes

from .helpers import case, suite


def test_a_pytest_style_file_is_read():
    run = parse_bytes(
        suite(
            case("test_a"),
            case("test_b", "fail", msg="x != y"),
            case("test_c", "skip"),
            case("test_d", "err"),
        ),
        "r",
    )
    assert {c.name: c.status for c in run.cases.values()} == {
        "test_a": "passed", "test_b": "failed", "test_c": "skipped", "test_d": "error",
    }  # fmt: skip
    assert run.cases["pkg.Mod::test_b"].message == "x != y"
    assert run.counts == {"passed": 1, "failed": 1, "error": 1, "skipped": 1}


def test_testsuite_as_root_nested_suites_and_namespaces():
    nested = b'<testsuite name="a"><testsuite name="b"><testcase classname="k" name="t1"/></testsuite><testcase name="t2"/></testsuite>'
    run = parse_bytes(nested, "r")
    assert set(run.cases) == {"k::t1", "t2"}
    ns = b'<testsuites xmlns="urn:x"><testsuite name="s"><testcase classname="c" name="t"><failure message="m"/></testcase></testsuite></testsuites>'
    assert parse_bytes(ns, "r").cases["c::t"].status == "failed"


def test_the_commit_is_read_from_a_property_under_any_of_its_usual_names():
    for prop in ("commit", "git.commit", "sha", "git_sha"):
        xml = f'<testsuite name="s"><properties><property name="{prop}" value="abc1234"/></properties></testsuite>'.encode()
        assert parse_bytes(xml, "r").commit == "abc1234", prop
    assert parse_bytes(b'<testsuite name="s"/>', "r").commit is None


def test_surefire_rerun_elements_count_as_retries_not_as_failures():
    xml = (
        b'<testsuite name="s"><testcase classname="c" name="t"><flakyFailure message="first"/><flakyError message="second"/></testcase>'
        b'<testcase classname="c" name="u"><failure message="always"/><rerunFailure message="again"/></testcase></testsuite>'
    )
    run = parse_bytes(xml, "r")
    assert run.cases["c::t"].status == "passed" and run.cases["c::t"].retries == ["first", "second"]
    assert run.cases["c::u"].status == "failed" and run.cases["c::u"].message == "always"


def test_failure_without_a_message_takes_its_first_line_or_its_kind():
    xml = b'<testsuite><testcase name="a"><failure>line one\nline two</failure></testcase><testcase name="b"><error/></testcase></testsuite>'
    run = parse_bytes(xml, "r")
    assert run.cases["a"].message == "line one"
    assert run.cases["b"].message == "error"


def test_the_same_test_twice_keeps_the_last_one_and_counts_the_duplicate():
    run = parse_bytes(suite(case("t"), case("t", "fail")), "r")
    assert run.duplicates == 1 and run.cases["pkg.Mod::t"].status == "failed"


def test_odd_times_are_zero_not_a_crash():
    for t in ("nan", "inf", "-5", "abc", "", "1e999", "1,5"):
        xml = f'<testsuite><testcase name="x" time="{t}"/></testsuite>'.encode()
        got = parse_bytes(xml, "r").cases["x"].seconds
        assert got in (0.0, 1.5), (t, got)


def test_control_characters_and_long_text_are_cleaned_and_cut():
    xml = (
        '<testsuite><testcase name="a"><failure message="bad&#8;&#27;[31mred">'
        + "x" * 9000
        + "</failure></testcase></testsuite>"
    ).encode()
    c = parse_bytes(xml, "r").cases["a"]
    assert "\x08" not in c.message and "\x1b" not in c.message
    assert len(c.details) <= junit.MAX_TEXT


def test_terminal_escape_codes_in_a_report_do_not_make_the_whole_file_unreadable():
    raw = b'<testsuite><testcase name="a"><failure message="\x1b[31mred\x1b[0m &#27; &#x1B; &#65; &#x1F600;"/></testcase></testsuite>'
    msg = parse_bytes(raw, "r").cases["a"].message
    assert "\x1b" not in msg and "red" in msg and "A" in msg and "\U0001f600" in msg


HOSTILE = {
    "doctype": b'<!DOCTYPE x [<!ENTITY a "b">]><testsuite><testcase name="&a;"/></testsuite>',
    "billion laughs": b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]><testsuite><testcase name="&lol2;"/></testsuite>',
    "external entity": b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><testsuite><testcase name="&xxe;"/></testsuite>',
    "external dtd": b'<!DOCTYPE testsuite SYSTEM "http://127.0.0.1:9/evil.dtd"><testsuite/>',
    "lowercase doctype": b"<!doctype testsuite><testsuite/>",
}


@pytest.mark.parametrize("name", HOSTILE)
def test_entities_and_doctypes_are_refused_before_anything_is_expanded(name):
    with pytest.raises(JUnitError, match="DOCTYPE or declares"):
        parse_bytes(HOSTILE[name], "r")


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"", "not valid XML"),
        (b"not xml at all", "not valid XML"),
        (b"<testsuite><testcase></testsuite>", "not valid XML"),
        (
            b'<?xml version="1.0" encoding="UTr-8"?><testsuite/>',
            "not valid XML: unknown encoding",
        ),  # found by the fuzzer
        (b"<html><body/></html>", "root element is <html>"),
        ("<testsuite/>".encode("utf-16"), "UTF-16"),
        (b"<testsuite>" + b"<a>" * 5000 + b"</testsuite>", "not valid XML"),
    ],
)
def test_input_that_is_not_junit_is_an_error_message_not_a_traceback(data, match):
    with pytest.raises(JUnitError, match=match):
        parse_bytes(data, "r")


def test_size_limits(monkeypatch):
    monkeypatch.setattr(junit, "MAX_BYTES", 100)
    with pytest.raises(JUnitError, match="larger than"):
        parse_bytes(b"<testsuite>" + b" " * 200 + b"</testsuite>", "r")
    monkeypatch.setattr(junit, "MAX_BYTES", 1 << 20)
    monkeypatch.setattr(junit, "MAX_CASES", 3)
    with pytest.raises(JUnitError, match="more than 3 test cases"):
        parse_bytes(suite(*(case(f"t{i}") for i in range(4))), "r")


def test_a_deep_but_valid_file_does_not_blow_the_stack():
    depth = 900
    xml = (
        b"<testsuites>"
        + b'<testsuite name="x">' * depth
        + b'<testcase name="t"/>'
        + b"</testsuite>" * depth
        + b"</testsuites>"
    )
    assert "t" in parse_bytes(xml, "r").cases


def test_read_reports_a_missing_file_and_a_directory(tmp_path):
    with pytest.raises(JUnitError, match="cannot read"):
        junit.read(tmp_path / "nope.xml")
    with pytest.raises(JUnitError, match="cannot read"):
        junit.read(tmp_path)


# ---- several files make one run -------------------------------------------------------------------------------


def test_files_of_one_run_are_merged_and_the_worst_result_wins(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "a.xml").write_bytes(suite(case("t1"), case("t2", "skip"), commit="c1"))
    (d / "b.xml").write_bytes(suite(case("t1", "fail"), case("t2"), case("t3")))
    run = junit.load([str(d)])[0]
    assert run.label == "run" and run.commit == "c1"
    assert {c.name: c.status for c in run.cases.values()} == {"t1": "failed", "t2": "passed", "t3": "passed"}
    assert run.duplicates == 2


def test_files_of_different_commits_cannot_be_one_run(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "a.xml").write_bytes(suite(case("t"), commit="c1"))
    (d / "b.xml").write_bytes(suite(case("u"), commit="c2"))
    with pytest.raises(JUnitError, match="different commits: c1, c2"):
        junit.load([str(d)])


def test_directories_are_walked_in_order_and_symlinks_and_other_files_are_ignored(tmp_path):
    d = tmp_path / "run"
    (d / "sub").mkdir(parents=True)
    (d / "b.xml").write_bytes(suite(case("b")))
    (d / "sub" / "a.XML").write_bytes(suite(case("a")))
    (d / "notes.txt").write_text("<not-xml")
    outside = tmp_path / "outside.xml"
    outside.write_bytes(suite(case("secret")))
    os.symlink(outside, d / "link.xml")
    run = junit.load([str(d)])[0]
    assert set(run.cases) == {"pkg.Mod::a", "pkg.Mod::b"}


def test_an_empty_directory_and_no_arguments_are_errors(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(JUnitError, match="no .xml files"):
        junit.load([str(tmp_path / "empty")])
    with pytest.raises(JUnitError, match="no test reports"):
        junit.load([])


def test_two_files_with_the_same_name_get_different_labels(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    for d in ("x", "y"):
        (tmp_path / d / "report.xml").write_bytes(suite(case("t")))
    labels = [r.label for r in junit.load([str(tmp_path / "x/report.xml"), str(tmp_path / "y/report.xml")])]
    assert len(set(labels)) == 2


def test_the_file_count_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(junit, "MAX_FILES", 2)
    d = tmp_path / "run"
    d.mkdir()
    for i in range(3):
        (d / f"{i}.xml").write_bytes(suite(case(f"t{i}")))
    with pytest.raises(JUnitError, match="more than 2 XML files"):
        junit.load([str(d)])


def test_a_failure_wins_over_a_skip_in_either_order_and_the_first_failure_is_kept():
    a = b'<testsuite><testcase name="t"><failure message="f1"/><skipped message="s"/><error message="e"/></testcase></testsuite>'
    b = b'<testsuite><testcase name="t"><skipped message="s"/><failure message="f1"/><error message="e"/></testcase></testsuite>'
    for xml in (a, b):
        c = parse_bytes(xml, "r").cases["t"]
        assert (c.status, c.message) == ("failed", "f1")


def test_the_total_case_limit_over_all_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(junit, "MAX_TOTAL_CASES", 5)
    paths = []
    for i in range(3):
        p = tmp_path / f"r{i}.xml"
        p.write_bytes(suite(case("a"), case("b")))
        paths.append(str(p))
    with pytest.raises(JUnitError, match="more than 5 test cases in all"):
        junit.load(paths)
    assert len(junit.load(paths[:2])) == 2
