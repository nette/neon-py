import json

import pytest
from corpus import Case, load_cases, runs_here
from typed import equal, to_host

from neon import NeonError, parse


def cases(category: str) -> list[Case]:
    return [c for c in load_cases(category) if runs_here(c)]


def ids(category: str) -> list[str]:
    return [c.name for c in cases(category)]


@pytest.mark.parametrize("case", cases("decode"), ids=ids("decode"))
def test_decode(case: Case) -> None:
    text = case.read(".neon")
    assert text is not None
    document = parse(text)
    assert document.print() == text
    actual = document.to_value()
    expected = to_host(json.loads(case.read(".json") or ""))
    assert equal(actual, expected), (actual, expected)


@pytest.mark.parametrize("case", cases("errors"), ids=ids("errors"))
def test_errors(case: Case) -> None:
    data = case.read_bytes(".neon")
    assert data is not None
    try:
        parse(data).to_value()
        actual = "accepted"
    except NeonError as e:
        assert e.position
        actual = f"{e.message}\n{e.position.line}:{e.position.column}\n"
    assert actual == case.read(".error")
