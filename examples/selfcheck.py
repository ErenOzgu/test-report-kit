#!/usr/bin/env python3
"""Runs the example suite many times and checks that test-report-kit finds exactly the tests that are flaky.

    python examples/selfcheck.py [RUNS]            (default 24)

The suite has one test that is flaky by a coin that can be computed from the run number, one that is flaky for
real (random.random), one that always fails, one that is always skipped and some that always pass. With 24 runs
the real coin flip shows both outcomes with probability 1 - 2 * 0.5**24, so this check is not itself flaky in
practice (about one in 8 million).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "suite"))

from test_suite import coin  # noqa: E402

EXPECTED_FLAKY = {"test_suite::test_flaky_by_seed", "test_suite::test_flaky_for_real"}
EXPECTED_FAILING = {"test_suite::test_always_fails"}
EXPECTED_SKIPPED = {"test_suite::test_always_skipped"}


def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(runs):
            env = dict(os.environ, SUITE_RUN=str(i), SUITE_COMMIT="selfcheck")
            subprocess.run(
                [
                    sys.executable, "-m", "pytest", ".", "-q", "-p", "no:cacheprovider",
                    "--rootdir", ".", "-o", "junit_family=xunit2", f"--junitxml={tmp}/run-{i:02d}.xml",
                ],
                env=env, capture_output=True, check=False, cwd=HERE / "suite",
            )  # fmt: skip
        files = sorted(str(p) for p in Path(tmp).glob("run-*.xml"))
        if len(files) != runs:
            print(f"only {len(files)} of {runs} reports were written")
            return 1
        out = subprocess.run(
            [sys.executable, "-m", "test_report_kit", "report", "--format", "json", *files],
            capture_output=True, text=True, check=True, cwd=HERE.parent,
        )  # fmt: skip
        doc = json.loads(out.stdout)
        found = {
            "flaky": {r["id"] for r in doc["flaky"]},
            "failing": {r["id"] for r in doc["failing"]},
            "skipped": {r["id"] for r in doc["skipped"]},
        }
        wanted = {"flaky": EXPECTED_FLAKY, "failing": EXPECTED_FAILING, "skipped": EXPECTED_SKIPPED}
        problems = [
            f"{k}: expected {sorted(wanted[k])}, found {sorted(found[k])}"
            for k in wanted
            if found[k] != wanted[k]
        ]
        # the coin that can be computed: the reported pattern has to be the computed one
        row = next(r for r in doc["flaky"] if r["id"] == "test_suite::test_flaky_by_seed")
        expected_pattern = "".join("." if coin("flaky_by_seed", i) else "F" for i in range(runs))
        if row["pattern"] != expected_pattern:
            problems.append(f"flaky_by_seed pattern: expected {expected_pattern}, found {row['pattern']}")
        gate = subprocess.run(
            [sys.executable, "-m", "test_report_kit", "flaky", *files],
            capture_output=True,
            text=True,
            check=False,
            cwd=HERE.parent,
        )
        if gate.returncode != 1:
            problems.append(f"the flaky gate should exit 1, it exited {gate.returncode}")
        if problems:
            print("\n".join(problems))
            return 1
    print(
        f"ok: {runs} runs, found {len(EXPECTED_FLAKY)} flaky, {len(EXPECTED_FAILING)} failing, {len(EXPECTED_SKIPPED)} skipped, exactly as built"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
