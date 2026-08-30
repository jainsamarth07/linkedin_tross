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


def _exp_card(rows):
    """
    Build an experience-card Flight payload from (kind, text) rows, mirroring
    the element types the real card uses:
      'h' -> HEADER  <p>                       (title / company / tenure line)
      'd' -> DETAIL  <p> with plain textProps  (date / location)
      'x' -> DESC    <p> with expandable text  (role blurb)
    """
    def node(kind, t):
        j = json.dumps(t)
        if kind == "h":
            return f'["$","p",null,{{"children":[{j}]}}]'
        if kind == "d":
            return f'["$","p",null,{{"textProps":{{"maxLineCountExpression":0,"children":[{j}]}}}}]'
        if kind == "x":
            return f'["$","p",null,{{"textProps":{{"expandButtonText":"more","children":[{j}]}}}}]'
        raise ValueError(kind)
    kids = ",".join(node(k, t) for k, t in rows)
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
    fl = _exp_card([
        ("h", "Experience"),
        ("h", "JPMorganChase"), ("h", "3 yrs 7 mos"),
        ("h", "Software Engineer II"), ("h", "Full-time"), ("d", "Nov 2025 - Present · 10 mos"),
        ("h", "Software Engineer"), ("h", "Full-time"), ("d", "Jul 2023 - Oct 2025 · 2 yrs 4 mos"),
        ("d", "Bengaluru"),
        ("h", "Software Engineer"), ("h", "Internship"), ("d", "Feb 2023 - Jun 2023 · 5 mos"),
        ("d", "Bengaluru, Karnataka, India"),
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


def test_parse_skills_needs_endorsement_lines():
    # a Part7 payload with positions / projects and NO endorsements -> nothing
    assert parse_skills(_flight([
        "Open-Source Software", "ThreatPad",
        "Threat Intelligence, Cyber Threat Intelligence, OSINT",
        "Threat Researcher - II at CloudSEK",
    ])) == []


def test_experience_group_then_standalone_entries():
    fl = _exp_card([
        ("h", "Experience"),
        ("h", "CloudSEK"), ("h", "3 yrs 1 mo"), ("d", "Bengaluru, Karnataka, India"),
        ("h", "Threat Researcher - II"), ("h", "Full-time"), ("d", "Apr 2026 - Present · 5 mos"), ("d", "On-site"),
        ("h", "Cyber Security Analyst"), ("h", "Internship"), ("d", "Aug 2023 - Nov 2023 · 4 mos"), ("d", "Hybrid"),
        ("h", "CTF Player"), ("h", "TryHackMe · Part-time"), ("d", "May 2020 - Jun 2024 · 4 yrs 2 mos"),
        ("h", "Cyber Security Intern"), ("h", "Haryana Police · Internship"), ("d", "Jun 2021 - Jul 2021 · 2 mos"),
        ("d", "Gurugram, Haryana, India"),
    ])
    exp = parse_experience(fl)
    got = [(e["title"], e["company"]) for e in exp]
    assert ("Threat Researcher - II", "CloudSEK") in got
    assert ("Cyber Security Analyst", "CloudSEK") in got
    assert ("CTF Player", "TryHackMe") in got          # group did NOT leak here
    assert ("Cyber Security Intern", "Haryana Police") in got
    assert not any(c == "CloudSEK" for t, c in got if t == "CTF Player")


def test_education_drops_certs_and_project_rows():
    fl = _flight([
        "Education",
        "Certified Ethical Hacker (CEH) Practical", "EC-Council",
        "Issued Apr 2022 · Expired Apr 2025", "Credential ID ECC9026814537",
        "Google Cloud Program", "Qwiklabs", "Issued Dec 2020",
        "DarkHuntAI", "ThreatPad",
        "Thapar Institute of Engineering & Technology",
        "Bachelor of Technology - BTech, Electrical Engineering", "2019 – 2024",
        "GitHub - bhavikmalhotra/ThreatPad: Open-source note-taking platform for teams.",
    ])
    edu = parse_education(fl)
    assert [e["school"] for e in edu] == ["Thapar Institute of Engineering & Technology"]
    assert edu[0]["duration"] == "2019 – 2024"


def test_employment_suffix_stripped():
    fl = _exp_card([
        ("h", "Experience"),
        ("h", "Engineer"), ("h", "Acme Corp · Full-time"),
        ("d", "Jan 2020 - Present · 6 yrs"), ("d", "Berlin Area · Hybrid"),
    ])
    e = parse_experience(fl)[0]
    assert e["title"] == "Engineer"
    assert e["company"] == "Acme Corp"
    assert e["location"] == "Berlin Area"


def test_experience_bulleted_descriptions_map_to_their_role():
    fl = _exp_card([
        ("h", "Experience"),
        ("h", "CloudSEK"), ("h", "Full-time · 3 yrs 1 mo"), ("d", "Bengaluru, Karnataka, India"),
        ("h", "Threat Researcher - II"), ("h", "Full-time"), ("d", "Apr 2026 - Present · 5 mos"), ("d", "On-site"),
        ("x", "• Built automation pipelines. • Led 55 engagements."),
        ("h", "Threat Researcher - I"), ("h", "Full-time"), ("d", "Dec 2023 - Mar 2026 · 2 yrs 4 mos"), ("d", "On-site"),
        ("x", "• Dark web investigations."),
    ])
    exp = parse_experience(fl)
    assert [e["title"] for e in exp] == ["Threat Researcher - II", "Threat Researcher - I"]
    assert all(e["company"] == "CloudSEK" for e in exp)
    assert exp[0]["description"] == "• Built automation pipelines. • Led 55 engagements."
    assert exp[1]["description"] == "• Dark web investigations."


def test_experience_inline_short_description():
    fl = _exp_card([
        ("h", "Experience"),
        ("h", "Software Engineer"), ("h", "Microsoft · Full-time"), ("d", "Nov 2025 - Present · 10 mos"),
        ("d", "Dublin, County Dublin, Ireland"),
        ("x", "Bringing Azure to Sovereign Clouds."),
        ("h", "Research Scholar"), ("h", "University of Galway · Internship"), ("d", "Jun 2023 - Aug 2023 · 3 mos"),
        ("d", "Galway, County Galway, Ireland · Hybrid"),
        ("x", "Used GANs and VAEs to synthesize spectroscopic data."),
    ])
    exp = parse_experience(fl)
    assert exp[0]["title"] == "Software Engineer" and exp[0]["company"] == "Microsoft"
    assert exp[0]["location"] == "Dublin, County Dublin, Ireland"
    assert exp[0]["description"] == "Bringing Azure to Sovereign Clouds."
    assert exp[1]["description"] == "Used GANs and VAEs to synthesize spectroscopic data."


def test_experience_media_and_linkcards_are_not_descriptions():
    fl = _exp_card([
        ("h", "Experience"),
        ("h", "Analyst"), ("h", "Mettl · Internship"), ("d", "Jan 2023 - Jun 2023 · 6 mos"),
        ("d", "Gurugram, Haryana, India"),
        ("h", "Internship certificate - Aditya Gupta.pdf"),
        ("h", "Founder"), ("h", "OnlyTools · Self-employed"), ("d", "Jan 2025 - Present · 1 yr 8 mos"),
        ("x", "Playstore - https://play.google.com/store/apps/details?id=com.x"),
    ])
    exp = parse_experience(fl)
    assert [e["title"] for e in exp] == ["Analyst", "Founder"]
    assert exp[0]["description"] is None
    assert exp[1]["description"] is None


def test_experience_entries_always_carry_a_description_key():
    exp = parse_experience(_load("card_experience.flight"))
    assert exp and all(e["description"] is None for e in exp)


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
