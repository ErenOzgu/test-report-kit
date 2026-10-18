from __future__ import annotations

import datetime as dt

import pytest

from test_report_kit import allowlist
from test_report_kit.allowlist import AllowlistError


def write(tmp_path, text):
    p = tmp_path / "allow.toml"
    p.write_text(text, encoding="utf-8")
    return p


GOOD = '[[allow]]\ntest = "pkg.Mod::test_*"\nuntil = 2026-12-01\nreason = "tracked in the tracker"\n'


def test_a_good_file_is_read(tmp_path):
    (e,) = allowlist.load(write(tmp_path, GOOD))
    assert e.until == dt.date(2026, 12, 1) and e.reason == "tracked in the tracker"
    assert (
        e.matches("pkg.Mod::test_a")
        and not e.matches("pkg.Other::test_a")
        and not e.matches("PKG.Mod::test_a")
    )


def test_expiry_is_inclusive_of_the_last_day(tmp_path):
    (e,) = allowlist.load(write(tmp_path, GOOD))
    assert not e.expired(dt.date(2026, 12, 1)) and e.expired(dt.date(2026, 12, 2))


def test_an_empty_file_is_an_empty_allowlist(tmp_path):
    assert allowlist.load(write(tmp_path, "# nothing yet\n")) == []


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ('[[allow]]\ntest = "t"\nreason = "r"\n', "'until' must be a date"),
        ('[[allow]]\ntest = "t"\nuntil = "2026-12-01"\nreason = "r"\n', "'until' must be a date"),
        ('[[allow]]\ntest = "t"\nuntil = 2026-12-01T10:00:00\nreason = "r"\n', "'until' must be a date"),
        ('[[allow]]\ntest = "t"\nuntil = 2026-12-01\n', "'reason'"),
        ('[[allow]]\ntest = "t"\nuntil = 2026-12-01\nreason = "  "\n', "'reason'"),
        ('[[allow]]\nuntil = 2026-12-01\nreason = "r"\n', "'test'"),
        ('[[allow]]\ntest = ""\nuntil = 2026-12-01\nreason = "r"\n', "'test'"),
        ('[[allow]]\ntest = 5\nuntil = 2026-12-01\nreason = "r"\n', "'test'"),
        ('[[allow]]\ntest = "t"\nuntil = 2026-12-01\nreason = "r"\nowner = "me"\n', "unknown key 'owner'"),
        ('allow = "all"\n', "array of tables"),
        ("allow = [1]\n", "not a table"),
        ("other = 1\n", "unknown top-level key 'other'"),
        ("not = = toml", "not valid TOML"),
    ],
)
def test_every_mistake_has_a_message_that_names_it(tmp_path, text, match):
    with pytest.raises(AllowlistError, match=match):
        allowlist.load(write(tmp_path, text))


def test_missing_oversized_and_non_utf8_files(tmp_path, monkeypatch):
    with pytest.raises(AllowlistError, match="cannot read"):
        allowlist.load(tmp_path / "missing.toml")
    bad = tmp_path / "bin.toml"
    bad.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(AllowlistError, match="not valid TOML"):
        allowlist.load(bad)
    monkeypatch.setattr(allowlist, "MAX_BYTES", 10)
    with pytest.raises(AllowlistError, match="larger than"):
        allowlist.load(write(tmp_path, GOOD))
