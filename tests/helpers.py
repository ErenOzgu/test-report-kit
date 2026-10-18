"""Small builders for JUnit XML, so each test shows only what it is about."""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr


def case(
    name: str, status: str = "ok", cls: str = "pkg.Mod", msg: str = "boom", t: float = 0.01, extra: str = ""
) -> str:
    a = f'classname={quoteattr(cls)} name={quoteattr(name)} time="{t}"'
    if status == "ok":
        return f"<testcase {a}>{extra}</testcase>"
    if status == "skip":
        return f"<testcase {a}><skipped message={quoteattr(msg)}/></testcase>"
    tag = {"fail": "failure", "err": "error"}[status]
    return f"<testcase {a}><{tag} message={quoteattr(msg)}>{escape(msg)}</{tag}>{extra}</testcase>"


def suite(*cases: str, commit: str | None = None, name: str = "s") -> bytes:
    props = f'<properties><property name="commit" value="{commit}"/></properties>' if commit else ""
    return f'<testsuites><testsuite name="{name}">{props}{"".join(cases)}</testsuite></testsuites>'.encode()


def write_runs(tmp_path, *bodies: bytes) -> list[str]:
    paths = []
    for i, b in enumerate(bodies):
        p = tmp_path / f"run-{i}.xml"
        p.write_bytes(b)
        paths.append(str(p))
    return paths
