from __future__ import annotations

import pytest

from test_report_kit import analyze as A
from test_report_kit.junit import parse_bytes

from .helpers import case, suite


def runs(*bodies):
    return [parse_bytes(b, f"r{i}") for i, b in enumerate(bodies)]


def verdicts(a):
    return {t.name: t.verdict for t in a.tests}


def test_the_four_verdicts():
    a = A.analyze(runs(
        suite(case("stable"), case("flaky"), case("failing", "fail"), case("skipped", "skip")),
        suite(case("stable"), case("flaky", "fail"), case("failing", "err"), case("skipped", "skip")),
        suite(case("stable"), case("flaky"), case("failing", "fail"), case("skipped", "skip")),
    ))  # fmt: skip
    assert verdicts(a) == {"stable": "stable", "flaky": "flaky", "failing": "failing", "skipped": "skipped"}
    t = next(t for t in a.tests if t.name == "flaky")
    assert (t.pattern, t.passes, t.fails) == (".F.", 2, 1)
    assert round(t.fail_rate, 3) == 0.333


def test_a_single_run_cannot_show_a_test_to_be_flaky_but_a_retry_inside_it_can():
    one = A.analyze(runs(suite(case("a", "fail"), case("b"), case("c", extra='<flakyFailure message="x"/>'))))
    assert verdicts(one) == {"a": "failing", "b": "stable", "c": "flaky"}
    assert next(t for t in one.tests if t.name == "c").pattern == "r"


def test_runs_of_different_commits_are_never_compared_with_each_other():
    a = A.analyze(runs(
        suite(case("t", "fail"), commit="old"),
        suite(case("t", "fail"), commit="old"),
        suite(case("t"), commit="new"),
        suite(case("t"), commit="new"),
    ))  # fmt: skip
    assert sorted((g.commit, g.tests[0].verdict) for g in a.groups) == [("new", "stable"), ("old", "failing")]
    assert "flaky" not in {t.verdict for t in a.tests}


def test_runs_without_a_commit_are_one_group():
    a = A.analyze(runs(suite(case("t")), suite(case("t", "fail"))))
    assert [g.commit for g in a.groups] == [A.UNSPECIFIED] and verdicts(a) == {"t": "flaky"}


def test_a_test_missing_from_some_runs_is_counted_as_absent_and_marked():
    a = A.analyze(runs(suite(case("a"), case("b")), suite(case("a")), suite(case("a"), case("b", "fail"))))
    b = next(t for t in a.tests if t.name == "b")
    assert (b.pattern, b.absent, b.verdict) == (".-F" if False else ".-F", 1, "flaky")


def test_tests_are_ordered_failing_first_then_by_failure_rate():
    a = A.analyze(runs(
        suite(case("z_ok"), case("a_flaky_rare"), case("b_flaky_often", "fail"), case("c_fail", "fail")),
        suite(case("z_ok"), case("a_flaky_rare"), case("b_flaky_often"), case("c_fail", "fail")),
        suite(case("z_ok"), case("a_flaky_rare", "fail"), case("b_flaky_often", "fail"), case("c_fail", "fail")),
    ))  # fmt: skip
    assert [t.name for t in a.groups[0].tests] == ["c_fail", "b_flaky_often", "a_flaky_rare", "z_ok"]


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("expected 5 got 7", "expected 6 got 9"),
        ("failed after 30.5s", "failed after 31.2s"),
        (
            "open /tmp/pytest-of-root/pytest-3/t/x.txt failed",
            "open /tmp/pytest-of-ci/pytest-9/t/x.txt failed",
        ),
        (
            "id 550e8400-e29b-41d4-a716-446655440000 missing",
            "id 123e4567-e89b-12d3-a456-426614174000 missing",
        ),
        ("at 0xdeadbeef", "at 0x7ffd1234"),
        ("started 2026-10-17T10:00:00Z", "started 2026-10-18 11:22:33.456+03:00"),
        ("token 3f9a1c2b7d4e8f0a1b2c3d4e5f6a7b8c bad", "token aaaaaaaaaaaaaaaaaaaaaaaa bad"),
        ("x   y\tz", "x y z"),
    ],
)
def test_messages_that_differ_only_in_what_changes_from_run_to_run_have_one_signature(a, b):
    assert A.signature_text(a) == A.signature_text(b)
    assert A.signature_id(A.signature_text(a)) == A.signature_id(A.signature_text(b))


def test_messages_about_different_things_have_different_signatures():
    texts = [
        "TimeoutError: gateway",
        "ConnectionError: gateway",
        "AssertionError: assert 1 == 2",
        "KeyError: 'cart'",
    ]
    assert len({A.signature_id(A.signature_text(t)) for t in texts}) == 4


def test_a_long_digit_run_is_a_number_not_a_hex_string_and_names_are_kept():
    assert A.signature_text("19.989999999999995 != 19.99") == "N != N"
    assert A.signature_text("user_42 not found in table2") == "user_42 not found in table2"


def test_only_the_first_line_and_300_characters_of_a_message_count():
    assert A.signature_text("first\nsecond") == "first"
    assert len(A.signature_text("x" * 1000)) == 300
    assert A.signature_text("") == "(no message)"
    assert A.signature_text("\n\n  \n") == "(no message)"


def test_signatures_count_failures_tests_and_runs():
    a = A.analyze(runs(
        suite(case("a", "fail", msg="boom 1"), case("b", "fail", msg="boom 2")),
        suite(case("a", "fail", msg="boom 3"), case("b")),
    ))  # fmt: skip
    (sig,) = a.signatures.values()
    assert (sig.count, len(sig.tests), len(sig.runs), sig.text) == (3, 2, 2, "boom N")


def test_retried_attempts_count_as_failures_for_the_rate_and_become_signatures():
    a = A.analyze(runs(suite(case("t", extra='<flakyFailure message="conn refused 5672"/>'))))
    (t,) = a.tests
    assert (t.retried, t.fails, t.passes, t.fail_rate) == (1, 0, 1, 0.5)
    assert [s.text for s in a.signatures.values()] == ["conn refused N"]


# ---- compare ---------------------------------------------------------------------------------------------------


def test_compare_finds_what_changed():
    before = A.analyze(runs(
        suite(case("fixed", "fail"), case("regress"), case("gone"), case("slow", t=1.0), case("wobble")),
        suite(case("fixed", "fail"), case("regress"), case("gone"), case("slow", t=1.0), case("wobble")),
    ))  # fmt: skip
    after = A.analyze(runs(
        suite(case("fixed"), case("regress", "fail"), case("new"), case("slow", t=3.0), case("wobble", "fail")),
        suite(case("fixed"), case("regress", "fail"), case("new"), case("slow", t=3.0), case("wobble")),
    ))  # fmt: skip
    c = A.compare(before, after)
    assert [x.id for x in c.newly_failing] == ["pkg.Mod::regress"]
    assert [x.id for x in c.fixed] == ["pkg.Mod::fixed"]
    assert [x.id for x in c.newly_flaky] == ["pkg.Mod::wobble"]
    assert c.new_tests == ["pkg.Mod::new"] and c.removed_tests == ["pkg.Mod::gone"]
    assert [(i, round(x), round(y)) for i, x, y in c.slower] == [("pkg.Mod::slow", 1, 3)]


def test_compare_ignores_small_absolute_slowdowns():
    before = A.analyze(runs(suite(case("t", t=0.001))))
    after = A.analyze(runs(suite(case("t", t=0.2))))
    assert A.compare(before, after).slower == []


def test_a_failing_test_that_is_now_skipped_is_not_fixed():
    before = A.analyze(runs(suite(case("t", "fail")), suite(case("t", "fail"))))
    after = A.analyze(runs(suite(case("t", "skip")), suite(case("t", "skip"))))
    c = A.compare(before, after)
    assert c.fixed == [] and c.newly_failing == []


def test_reruns_of_a_test_that_failed_for_good_do_not_count_as_passes_in_the_rate():
    a = A.analyze(
        runs(
            suite(case("t", "fail", extra='<rerunFailure message="again"/><rerunFailure message="again"/>')),
            suite(case("t")),
        )
    )
    (t,) = a.tests
    assert (t.verdict, t.retried, t.fail_rate) == ("flaky", 0, 0.5)
