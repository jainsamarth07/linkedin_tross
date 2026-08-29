"""
Parser tests against real captured React-Flight card payloads
(tests/captures/*.flight — Bill Gates / Satya Nadella public profiles,
Aug 2026). These lock the extraction logic against the actual shapes.
"""

from pathlib import Path

import pytest

import json

from app.flight_parser import (
    is_self_view,
    parse_about,
    parse_education,
    parse_experience,
    parse_skills,
    split_date_range,
    text_leaves,
)


def _flight(leaves):
    kids = ",".join(
        f'["$","p",null,{{"children":[{json.dumps(l)}]}}]' for l in leaves
    )
    return '0:["$","div",null,{"children":[' + kids + "]}]"

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


def test_self_view_detected_and_produces_no_garbage_education():
    # self-view Education card: the section header is immediately followed by
    # the "Connected apps" management widget and analytics chrome
    sv = (
        '0:["$","div",null,{"children":['
        '["$","p",null,{"children":["Education"]}],'
        '["$","p",null,{"children":["Connected apps"]}],'
        '["$","p",null,{"children":["Add the products you use to stand out."]}],'
        '["$","p",null,{"children":["156 profile views"]}],'
        '["$","p",null,{"children":["34 post impressions"]}],'
        '["$","p",null,{"children":["Credential ID ABC123"]}]'
        ']}]'
    )
    assert is_self_view(sv) is True
    # nothing trustworthy to extract -> empty, not garbage
    assert parse_education(sv) == []


def test_junk_and_standalone_cert_rows_filtered_from_education():
    fl = (
        '0:["$","div",null,{"children":['
        '["$","p",null,{"children":["Education"]}],'
        '["$","p",null,{"children":["Add credential"]}],'
        '["$","p",null,{"children":["MIT"]}],'
        '["$","p",null,{"children":["2010 – 2014"]}],'
        '["$","p",null,{"children":["AWS Certified Solutions Architect"]}]'
        ']}]'
    )
    edu = parse_education(fl)
    schools = [e["school"] for e in edu]
    assert schools == ["MIT"]  # junk prefix + trailing dateless cert dropped
    assert edu[0]["duration"] == "2010 – 2014"


def test_not_self_view_for_third_party_capture():
    assert is_self_view(_load("card_experience.flight")) is False


def test_parse_experience_company_grouped():
    # 3 roles at one employer, rendered as a group header + bare tenure
    fl = _flight([
        "Experience",
        "JPMorganChase", "3 yrs 7 mos",
        "Software Engineer II", "Full-time", "Nov 2025 - Present · 10 mos",
        "Software Engineer", "Full-time", "Jul 2023 - Oct 2025 · 2 yrs 4 mos",
        "Bengaluru",
        "Software Engineer", "Internship", "Feb 2023 - Jun 2023 · 5 mos",
        "Bengaluru, Karnataka, India",
    ])
    exp = parse_experience(fl)
    assert [e["title"] for e in exp] == [
        "Software Engineer II", "Software Engineer", "Software Engineer"]
    assert all(e["company"] == "JPMorganChase" for e in exp)
    assert exp[1]["location"] == "Bengaluru"
    assert exp[2]["location"] == "Bengaluru, Karnataka, India"


def test_parse_skills_with_endorsements():
    fl = _flight([
        "Cloud Foundry", "Endorsed by 1 person in the last 6 months", "1 endorsement",
        "Infrastructure as a Service (IaaS)", "1 endorsement",
        "Python", "12 endorsements",
        "Kubernetes",
    ])
    sk = parse_skills(fl)
    assert [(s["name"], s["endorsement_count"]) for s in sk] == [
        ("Cloud Foundry", 1),
        ("Infrastructure as a Service (IaaS)", 1),
        ("Python", 12),
        ("Kubernetes", None),
    ]


def test_parse_skills_wrong_card_returns_empty():
    assert parse_skills(_flight(["Interests", "Bill & Melinda Gates Foundation"])) == []


def test_employment_suffix_stripped():
    fl = (
        '0:["$","div",null,{"children":['
        '["$","p",null,{"children":["Experience"]}],'
        '["$","p",null,{"children":["Engineer"]}],'
        '["$","p",null,{"children":["Acme Corp · Full-time"]}],'
        '["$","p",null,{"children":["Jan 2020 - Present · 6 yrs"]}],'
        '["$","p",null,{"children":["Berlin Area · Hybrid"]}]'
        ']}]'
    )
    e = parse_experience(fl)[0]
    assert e["company"] == "Acme Corp"
    assert e["location"] == "Berlin Area"


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
