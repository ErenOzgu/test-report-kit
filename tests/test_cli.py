from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_report_kit import cli

from .fakes import FakeAnthropic
from .helpers import case, suite, write_runs

ROOT = Path(__file__).resolve().parent.parent


def run(*args, expect=None, capsys=None):
    code = cli.main([str(a) for a in args])
    out = capsys.readouterr() if capsys else None
    if expect is not None:
        assert code == expect, out
    return code, out


@pytest.fixture
def flaky_runs(tmp_path):
    return write_runs(
        tmp_path,
        suite(case("a"), case("b", "fail"), case("c", "fail"), commit="x"),
        suite(case("a"), case("b"), case("c", "fail"), commit="x"),
        suite(case("a"), case("b", "fail"), case("c", "fail"), commit="x"),
    )


def test_report_prints_markdown_to_standard_output(flaky_runs, capsys):
    _, out = run("report", *flaky_runs, expect=0, capsys=capsys)
    assert out.out.startswith("# Test report") and "pkg.Mod::b" in out.out and out.err == ""


@pytest.mark.parametrize("fmt", ["md", "html", "json"])
def test_report_writes_each_format_to_a_file_atomically(flaky_runs, tmp_path, fmt):
    target = tmp_path / f"out.{fmt}"
    target.write_text("old")
    assert cli.main(["report", *flaky_runs, "--format", fmt, "-o", str(target)]) == 0
    text = target.read_text(encoding="utf-8")
    assert text != "old" and "pkg.Mod::b" in text
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".trk-")], "a temporary file was left"


def test_the_output_may_not_be_one_of_the_inputs(flaky_runs, capsys):
    code, out = run("report", *flaky_runs, "-o", flaky_runs[0], capsys=capsys)
    assert code == 2 and "is one of the inputs" in out.err
    assert "<testsuites>" in Path(flaky_runs[0]).read_text()


def test_the_output_may_not_be_a_directory(flaky_runs, tmp_path, capsys):
    code, out = run("report", *flaky_runs, "-o", tmp_path, capsys=capsys)
    assert code == 2 and "not a regular file" in out.err


def test_a_missing_input_is_exit_2_with_a_message_and_no_traceback(tmp_path, capsys):
    code, out = run("report", tmp_path / "nope.xml", capsys=capsys)
    assert code == 2 and "cannot read" in out.err and "Traceback" not in out.err


def test_top_is_range_checked(flaky_runs, capsys):
    for bad in ("-1", "5000"):
        code, out = run("report", *flaky_runs, "--top", bad, capsys=capsys)
        assert code == 2 and "--top" in out.err


# ---- the flaky gate -------------------------------------------------------------------------------------------


def test_the_gate_fails_on_a_flaky_test_and_names_it(flaky_runs, capsys):
    code, out = run("flaky", *flaky_runs, capsys=capsys)
    assert code == 1
    assert "FLAKY    pkg.Mod::b" in out.out and "F.F" in out.out and "pkg.Mod::c" not in out.out
    assert "1 test(s) block the gate across 3 runs." in out.out


def test_the_gate_can_also_fail_on_tests_that_always_fail(flaky_runs, capsys):
    code, out = run("flaky", *flaky_runs, "--fail-on", "both", capsys=capsys)
    assert code == 1 and "FAILING  pkg.Mod::c" in out.out and "FLAKY    pkg.Mod::b" in out.out
    code, out = run("flaky", *flaky_runs, "--fail-on", "failing", capsys=capsys)
    assert code == 1 and "pkg.Mod::b" not in out.out


def test_the_gate_passes_when_nothing_is_flaky(tmp_path, capsys):
    paths = write_runs(tmp_path, suite(case("a"), case("c", "fail")), suite(case("a"), case("c", "fail")))
    code, out = run("flaky", *paths, capsys=capsys)
    assert code == 0 and out.out.startswith("ok: no blocking tests across 2 runs")


def test_one_run_is_not_enough_to_judge_and_that_is_an_input_error_not_a_pass(tmp_path, capsys):
    (p,) = write_runs(tmp_path, suite(case("a"), commit="x"))
    code, out = run("flaky", p, capsys=capsys)
    assert code == 2 and "at least 2 runs of the same code" in out.err
    assert run("flaky", p, "--min-runs", "1", capsys=capsys)[0] == 0


def test_every_commit_group_needs_enough_runs(tmp_path, capsys):
    paths = write_runs(
        tmp_path, suite(case("a"), commit="x"), suite(case("a"), commit="x"), suite(case("a"), commit="y")
    )
    code, out = run("flaky", *paths, capsys=capsys)
    assert code == 2 and "commit y" in out.err


def allow(tmp_path, until="2099-01-01", test="pkg.Mod::b", reason="tracked"):
    p = tmp_path / "allow.toml"
    p.write_text(f'[[allow]]\ntest = "{test}"\nuntil = {until}\nreason = "{reason}"\n')
    return str(p)


def test_an_allowlisted_flaky_test_does_not_fail_the_gate_but_is_still_listed(flaky_runs, tmp_path, capsys):
    code, out = run("flaky", *flaky_runs, "--allowlist", allow(tmp_path), capsys=capsys)
    assert code == 0 and "allowed  pkg.Mod::b" in out.out and "until 2099-01-01 (tracked)" in out.out


def test_an_expired_entry_fails_the_gate_again(flaky_runs, tmp_path, capsys):
    code, out = run(
        "flaky",
        *flaky_runs,
        "--allowlist",
        allow(tmp_path, "2026-01-01"),
        "--today",
        "2026-06-01",
        capsys=capsys,
    )
    assert code == 1 and "EXPIRED  pkg.Mod::b  allowed until 2026-01-01" in out.out
    code, out = run(
        "flaky",
        *flaky_runs,
        "--allowlist",
        allow(tmp_path, "2026-06-01"),
        "--today",
        "2026-06-01",
        capsys=capsys,
    )
    assert code == 0


def test_an_entry_that_matches_nothing_is_reported_and_can_fail_the_gate(flaky_runs, tmp_path, capsys):
    a = allow(tmp_path, test="pkg.Mod::gone")
    code, out = run("flaky", *flaky_runs, "--allowlist", a, capsys=capsys)
    assert code == 1  # b is flaky and not allowed
    paths = write_runs(tmp_path, suite(case("a")), suite(case("a")))
    code, out = run("flaky", *paths, "--allowlist", a, capsys=capsys)
    assert code == 0 and "unused" in out.out and "remove it" in out.out
    assert run("flaky", *paths, "--allowlist", a, "--strict-allowlist", capsys=capsys)[0] == 1


def test_the_allowlist_only_covers_the_kind_of_test_the_gate_is_about(flaky_runs, tmp_path, capsys):
    a = allow(tmp_path, test="pkg.Mod::c")  # c fails every time; the default gate is about flaky tests
    code, out = run("flaky", *flaky_runs, "--allowlist", a, capsys=capsys)
    assert code == 1 and "unused" in out.out


def test_a_bad_allowlist_or_date_is_exit_2(flaky_runs, tmp_path, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text("[[allow]]\ntest = 'x'\n")
    assert run("flaky", *flaky_runs, "--allowlist", bad, capsys=capsys)[0] == 2
    code, out = run("flaky", *flaky_runs, "--today", "yesterday", capsys=capsys)
    assert code == 2 and "--today" in out.err
    assert run("flaky", *flaky_runs, "--min-runs", "0", capsys=capsys)[0] == 2


def test_the_gate_json_has_the_same_facts(flaky_runs, tmp_path, capsys):
    code, out = run(
        "flaky",
        *flaky_runs,
        "--allowlist",
        allow(tmp_path, test="pkg.Mod::zzz"),
        "--format",
        "json",
        capsys=capsys,
    )
    doc = json.loads(out.out)
    assert code == 1 and [b["id"] for b in doc["blocked"]] == ["pkg.Mod::b"] and doc["runs"] == 3
    assert doc["unused_allowlist"][0]["test"] == "pkg.Mod::zzz"


# ---- compare --------------------------------------------------------------------------------------------------


def test_compare_exit_code_follows_regressions_only_when_asked(tmp_path, capsys):
    before = write_runs(tmp_path, suite(case("a"), case("b", "fail")))
    (tmp_path / "after").mkdir()
    after = [str(tmp_path / "after" / "r.xml")]
    Path(after[0]).write_bytes(suite(case("a", "fail"), case("b")))
    code, out = run("compare", "--before", *before, "--after", *after, capsys=capsys)
    assert code == 0 and "## Newly failing (1)" in out.out and "## Fixed (1)" in out.out
    assert (
        run("compare", "--before", *before, "--after", *after, "--fail-on-regression", capsys=capsys)[0] == 1
    )
    code, out = run("compare", "--before", *before, "--after", *after, "--format", "json", capsys=capsys)
    assert json.loads(out.out)["newly_failing"] == ["pkg.Mod::a"]


# ---- --summarize ----------------------------------------------------------------------------------------------


def test_summarize_adds_a_checked_section(flaky_runs, monkeypatch, capsys):
    from test_report_kit import analyze, junit, view

    v = view.build(analyze.analyze(junit.load(flaky_runs)))
    sid = v["signatures"][0]["id"]
    server = FakeAnthropic(
        json.dumps(
            {
                "summary": "Two tests fail.",
                "clusters": [{"signatures": [sid], "likely_cause": "c", "next_step": "n"}],
            }
        )
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", server.url)
    try:
        _, out = run("report", *flaky_runs, "--summarize", expect=0, capsys=capsys)
    finally:
        server.close()
    assert "## AI-written triage" in out.out and "Two tests fail." in out.out and f"`{sid}`" in out.out


def test_summarize_without_a_key_still_writes_the_report_and_says_why(flaky_runs, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _, out = run("report", *flaky_runs, "--summarize", expect=0, capsys=capsys)
    assert (
        "## Failing in every run" in out.out
        and "Not available: `--summarize needs ANTHROPIC_API_KEY in the environment`" in out.out
    )
    assert "the AI summary was skipped" in out.err


def test_without_summarize_nothing_is_ever_sent(flaky_runs, monkeypatch, capsys):
    server = FakeAnthropic("{}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", server.url)
    try:
        run("report", *flaky_runs, expect=0, capsys=capsys)
        run("flaky", *flaky_runs, capsys=capsys)
    finally:
        server.close()
    assert server.requests == []


# ---- the installed command --------------------------------------------------------------------------------------


def test_the_module_entry_point_and_version(flaky_runs):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    r = subprocess.run(
        [sys.executable, "-m", "test_report_kit", "--version"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0 and r.stdout.startswith("test-report-kit 0.")
    r = subprocess.run(
        [sys.executable, "-m", "test_report_kit", "flaky", *flaky_runs],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 1


def test_no_command_and_unknown_options_are_exit_2_from_argparse():
    for argv in ([], ["report"], ["report", "--nope", "x"], ["flaky", "x", "--fail-on", "sometimes"]):
        with pytest.raises(SystemExit) as e:
            cli.main(argv)
        assert e.value.code == 2


def test_a_failed_write_leaves_neither_a_temporary_file_nor_a_half_written_report(
    flaky_runs, tmp_path, monkeypatch, capsys
):
    target = tmp_path / "out.md"
    target.write_text("old")

    def boom(*args):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cli.os, "replace", boom)
    code, out = run("report", *flaky_runs, "-o", target, capsys=capsys)
    assert code == 2 and "No space left" in out.err
    assert target.read_text() == "old"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".trk-")] == []
