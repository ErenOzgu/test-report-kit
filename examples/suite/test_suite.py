"""A small suite that behaves in known ways, to check the kit against: it has to find exactly the flaky ones.

SUITE_RUN is the number of the run. ``test_flaky_by_seed`` is flaky in a way that can be computed from the run
number, so a test can say beforehand which runs it fails in. ``test_flaky_for_real`` really is random.
"""

import os
import random
import time

import pytest

RUN = int(os.environ.get("SUITE_RUN", "0"))


def coin(name: str, run: int, p: float = 0.5) -> bool:
    """True with probability p, the same answer every time for the same name and run."""
    return random.Random(f"{name}:{run}").random() < p


def test_always_passes():
    assert sum(range(10)) == 45


def test_also_passes():
    assert "abc".upper() == "ABC"


def test_always_fails():
    assert 1 + 1 == 3, "arithmetic is broken in a way that is the same every run"


@pytest.mark.skip(reason="needs hardware that CI does not have")
def test_always_skipped():
    raise AssertionError("never runs")


def test_flaky_by_seed():
    assert coin("flaky_by_seed", RUN), f"the coin said no in run {RUN}"


def test_flaky_for_real():
    assert random.random() < 0.5, "a real coin flip came up tails"


def test_takes_a_moment():
    time.sleep(0.05)
