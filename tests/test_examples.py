from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "examples" / "suite"))

from test_suite import coin  # noqa: E402


def test_the_committed_example_outputs_are_what_the_tool_prints_today():
    r = subprocess.run(
        ["bash", str(ROOT / "examples" / "generate.sh"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=dict(
            os.environ, PYTHONPATH=str(ROOT), PATH=f"{Path(sys.executable).parent}:{os.environ['PATH']}"
        ),
        check=False,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_example_files_contain_nothing_but_made_up_data():
    for p in (ROOT / "examples").rglob("*.xml"):
        text = p.read_text(encoding="utf-8")
        for bad in ("@", "password", "token", "secret", "/home/", "C:\\"):
            assert bad not in text.replace("/srv/ci/work/app/", ""), (p, bad)


def test_the_example_suite_is_found_flaky_by_the_computed_coin(tmp_path):
    runs = 6
    for i in range(runs):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                ".",
                "-q",
                "-p",
                "no:cacheprovider",
                "--rootdir",
                ".",
                "-o",
                "junit_family=xunit2",
                f"--junitxml={tmp_path}/r{i}.xml",
            ],
            cwd=ROOT / "examples" / "suite",
            env=dict(os.environ, SUITE_RUN=str(i), SUITE_COMMIT="t"),
            capture_output=True,
            check=False,
        )
    files = sorted(str(p) for p in tmp_path.glob("r*.xml"))
    out = subprocess.run(
        [sys.executable, "-m", "test_report_kit", "report", "--format", "json", *files],
        cwd=ROOT,
        env=dict(os.environ, PYTHONPATH=str(ROOT)),
        capture_output=True,
        text=True,
        check=True,
    )
    doc = json.loads(out.stdout)
    row = next(r for r in doc["flaky"] if r["id"] == "test_suite::test_flaky_by_seed")
    assert row["pattern"] == "".join("." if coin("flaky_by_seed", i) else "F" for i in range(runs))
    assert [r["id"] for r in doc["failing"]] == ["test_suite::test_always_fails"]
    assert [r["id"] for r in doc["skipped"]] == ["test_suite::test_always_skipped"]
    assert doc["runs"]["commits"] == ["t"]
