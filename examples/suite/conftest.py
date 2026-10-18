"""Tags the JUnit file with the commit, the way a CI job would."""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _commit(record_testsuite_property):
    record_testsuite_property("commit", os.environ.get("SUITE_COMMIT", "demo"))
