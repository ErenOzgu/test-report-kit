"""The README makes claims about the code and quotes its output. These keep both honest.

``python tests/test_readme.py`` prints the detection table, to paste between the markers in README.md.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from test_report_kit.cli import build_parser  # noqa: E402

README = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""


def test_quoted_outputs_are_the_committed_example_files():
    found = re.findall(r"<!-- include:(\S+) -->\n```text\n(.*?)\n```", README, re.DOTALL)
    assert {p for p, _ in found} == {"examples/out/flaky.txt", "examples/out/flaky-allowlist.txt"}
    for path, text in found:
        assert text == (ROOT / path).read_text(encoding="utf-8").rstrip("\n"), path


def test_the_excerpt_of_the_report_is_the_start_of_the_committed_report():
    m = re.search(r"<!-- excerpt:(\S+) -->\n(.*?)\n<!-- /excerpt -->", README, re.DOTALL)
    assert m
    assert m.group(2) in (ROOT / m.group(1)).read_text(encoding="utf-8")


def detect_table() -> str:
    rows = ["| Fails in | 3 runs | 5 runs | 10 runs | 20 runs | 50 runs |", "|---|---:|---:|---:|---:|---:|"]
    for p in (0.5, 0.2, 0.1, 0.05, 0.01):
        cells = " | ".join(f"{100 * (1 - (1 - p) ** n):.1f} %" for n in (3, 5, 10, 20, 50))
        rows.append(f"| {p * 100:g} % of runs | {cells} |")
    return "\n".join(rows)


def test_the_probability_table_is_what_the_formula_says():
    m = re.search(r"<!-- detect:start -->\n(.*?)\n<!-- detect:end -->", README, re.DOTALL)
    assert m and m.group(1) == detect_table()


def options() -> dict[str, set[str]]:
    parser = build_parser()
    out = {"": {o for a in parser._actions for o in a.option_strings if o not in ("-h", "--help")}}  # noqa: SLF001
    for a in parser._actions:  # noqa: SLF001
        for name, sub in (
            getattr(a, "choices", {}).items() if hasattr(a, "choices") and isinstance(a.choices, dict) else []
        ):
            out[name] = {o for x in sub._actions for o in x.option_strings if o not in ("-h", "--help")}  # noqa: SLF001
    return out


def test_every_option_is_in_the_readme_and_every_documented_option_exists():
    opts = options()
    assert set(opts) == {"", "report", "flaky", "compare"}
    real = set().union(*opts.values())
    missing = [o for o in sorted(real) if o != "--version" and f"`{o}`" not in README]
    assert not missing, f"not documented: {missing}"
    documented = set(re.findall(r"^\| `(--[a-z-]+)`", README, re.MULTILINE))
    assert documented and documented <= real, documented - real


def test_each_options_table_lists_the_options_of_its_command():
    opts = options()
    for command in ("report", "flaky", "compare"):
        section = re.search(rf"\*\*{command}\*\*\n\n(.*?)(?:\n\n|\Z)", README, re.DOTALL)
        assert section, command
        listed = set(
            re.findall(
                r"`(--?[a-z][a-z-]*)`",
                "\n".join(ln.split("|")[1] for ln in section.group(1).splitlines()[2:]),
            )
        )
        assert listed == opts[command], (command, listed ^ opts[command])


def test_the_exit_statuses_in_the_readme_are_the_ones_the_code_uses():
    from test_report_kit import cli

    assert (cli.EXIT_OK, cli.EXIT_FAIL, cli.EXIT_USAGE) == (0, 1, 2)
    assert "Exit status: 0 ok, 1 the gate failed" in README and "2 an input, file or usage error" in README


def run_sh(script: str, cwd: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ, PYTHONPATH=str(ROOT), **(extra_env or {}))
    return subprocess.run(
        ["bash", "-ec", script], cwd=cwd, capture_output=True, text=True, env=env, check=False, timeout=120
    )


def test_the_try_it_command_runs_and_starts_the_report():
    line = re.search(r"^(test-report-kit report examples/runs/before/\*\.xml .*)$", README, re.MULTILINE)
    assert line
    r = run_sh(line.group(1).replace("test-report-kit", f"{sys.executable} -m test_report_kit"), ROOT)
    assert r.returncode == 0 and r.stdout.startswith("# Checkout service: 4 runs of one commit")


def run_blocks(yaml_text: str) -> list[str]:
    """The shell text of every ``run:`` of a short workflow snippet."""
    lines, out, i = yaml_text.splitlines(), [], 0
    while i < len(lines):
        m = re.match(r"^(\s*)(?:- )?run: (\|)?(.*)$", lines[i])
        i += 1
        if not m:
            continue
        if not m.group(2):
            out.append(m.group(3))
            continue
        body = []
        while i < len(lines) and (
            not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > len(m.group(1))
        ):
            body.append(lines[i])
            i += 1
        indent = min(len(b) - len(b.lstrip()) for b in body if b.strip())
        out.append("\n".join(b[indent:] for b in body))
    return out


def test_the_ci_snippet_in_the_readme_works_on_the_example_suite(tmp_path):
    steps = run_blocks(re.search(r"```yaml\n(.*?)```", README, re.DOTALL).group(1))
    assert len(steps) == 3, steps
    suite = ROOT / "examples" / "suite"
    py = shlex.quote(sys.executable)
    pytest = f"{py} -m pytest {suite} --rootdir {suite} -p no:cacheprovider"
    kit = f"{py} -m test_report_kit"
    first, second, third = (
        s.replace("test-report-kit", kit).replace("pytest -o", pytest + " -o") for s in steps
    )
    (tmp_path / "flaky-allowlist.toml").write_text(
        '[[allow]]\ntest = "test_suite::test_flaky_*"\nuntil = 2099-01-01\nreason = "synthetic"\n'
        '[[allow]]\ntest = "test_suite::test_always_fails"\nuntil = 2099-01-01\nreason = "synthetic"\n'
    )
    r = run_sh(first, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(p.name for p in (tmp_path / "reports").glob("run-*.xml")) == [
        f"run-{i}.xml" for i in range(1, 6)
    ]
    r = run_sh(second, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "reports" / "index.html").read_text().startswith("<!doctype html>")
    r = run_sh(third, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr  # everything that blocks is allowlisted
    assert "allowed  test_suite::test_always_fails" in r.stdout


def test_the_limits_in_the_readme_are_the_ones_in_the_code():
    from test_report_kit import junit

    assert (junit.MAX_BYTES >> 20, junit.MAX_CASES, junit.MAX_FILES, junit.MAX_TOTAL_CASES) == (
        64,
        200_000,
        5000,
        2_000_000,
    )
    for text in ("64 MiB", "200 000 test cases", "5 000 files and 2 million cases"):
        assert text in README


def test_the_ai_limits_in_the_readme_are_the_ones_in_the_code():
    from test_report_kit import summary

    assert summary.FIELD_CHARS == 500 and "500 characters" in README


if __name__ == "__main__":
    print(detect_table())
