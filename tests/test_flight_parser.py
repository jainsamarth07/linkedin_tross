"""
Parser tests against real captured React-Flight card payloads
(tests/captures/*.flight — Bill Gates / Satya Nadella public profiles,
Aug 2026). These lock the extraction logic against the actual shapes.
"""

from pathlib import Path

import pytest

from app.flight_parser import (
    parse_about,
    parse_education,
    parse_experience,
    split_date_range,
    text_leaves,
)

CAP = Path(__file__).parent / "captures"


def _load(name: str) -> str:
    p = CAP / name
    if not p.exists():
        pytest.skip(f"capture {name} not present")
    return p.read_text(encoding="utf-8", errors="replace")


def test_text_leaves_are_ordered_and_clean():
    lv = text_leaves(_load("card_experience.flight"))
    assert lv[0] == "Experience"
    assert "Microsoft" in lv
    assert all(not x.startswith("$") for x in lv)


def test_parse_about():
    about = parse_about(_load("card_about.flight"))
    assert about and about.startswith("Chair of the Gates Foundation")
    assert "Microsoft" in about


def test_parse_experience_simple():
    exp = parse_experience(_load("card_experience.flight"))
    assert [(e["title"], e["company"]) for e in exp] == [
        ("Co-chair", "Gates Foundation"),
        ("Founder", "Breakthrough Energy"),
        ("Co-founder", "Microsoft"),
    ]
    s, e = split_date_range(exp[0]["duration"])
    assert (s, e) == ("2000", None)


def test_parse_experience_grouped_and_board_roles():
    exp = parse_experience(_load("card_experience_grouped.flight"))
    titles = [e["title"] for e in exp]
    assert "Chairman and CEO" in titles
    assert "Member Board Of Trustees" in titles
    # the trailing location line must not become its own entry
    assert "Greater Seattle Area" not in titles
    ceo = next(e for e in exp if e["title"] == "Chairman and CEO")
    assert ceo["company"] == "Microsoft"
    assert ceo["location"] == "Greater Seattle Area"
    assert split_date_range(ceo["duration"]) == ("Feb 2014", None)
    starbucks = next(e for e in exp if e["company"] == "Starbucks")
    assert split_date_range(starbucks["duration"]) == ("2017", "2024")


def test_parse_education():
    edu = parse_education(_load("card_education.flight"))
    schools = [e["school"] for e in edu]
    assert "Harvard University" in schools
    assert "Lakeside School" in schools
    harvard = next(e for e in edu if e["school"] == "Harvard University")
    assert split_date_range(harvard["duration"]) == ("1973", "1975")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2000 – Present", ("2000", None)),
        ("1973 – 1975", ("1973", "1975")),
        ("Feb 2014 - Present · 12 yrs 7 mos", ("Feb 2014", None)),
        ("2017 – 2024", ("2017", "2024")),
        (None, (None, None)),
    ],
)
def test_split_date_range(raw, expected):
    assert split_date_range(raw) == expected
