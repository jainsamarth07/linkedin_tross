from app.parser import parse_profile_view
from tests.fixtures import MOCK_PROFILE_VIEW

URL = "https://www.linkedin.com/in/ada-lovelace/"
TS = "2026-08-27T00:00:00+00:00"


def parse():
    return parse_profile_view(MOCK_PROFILE_VIEW, URL, TS)


def test_summary_fields():
    p = parse()
    assert p.profile_url == URL
    assert p.name == "Ada Lovelace"
    assert p.headline.startswith("Mathematician")
    assert p.location == "London, England, United Kingdom"
    assert p.about.startswith("Fascinated")
    assert p.scraped_at == TS


def test_images_pick_largest_artifact():
    p = parse()
    assert p.images.profile_photo_url == (
        "https://media.licdn.com/dms/image/pp/800_800/x.jpg"
    )
    assert p.images.background_photo_url == (
        "https://media.licdn.com/dms/image/bg/1400_425/y.jpg"
    )


def test_experience():
    p = parse()
    assert len(p.experience) == 2
    first = p.experience[0]
    assert first.title == "Collaborator"
    assert first.company == "Analytical Engine Project"
    assert first.employment_type == "Full-time"
    assert first.start_date == "01/1842"
    assert first.end_date == "12/1843"
    assert first.duration == "01/1842 - 12/1843"
    # ongoing role -> "Present"
    assert p.experience[1].duration == "06/1843 - Present"


def test_education():
    p = parse()
    assert len(p.education) == 1
    edu = p.education[0]
    assert edu.school == "Private tutoring"
    assert edu.degree == "Mathematics & Science"
    assert edu.field_of_study == "Mathematics"
    assert edu.duration == "1833 - 1840"


def test_skills_and_endorsements():
    p = parse()
    names = {s.name: s.endorsement_count for s in p.skills}
    assert names == {"Analytical Engines": 42, "Technical Writing": None}


def test_certifications():
    p = parse()
    assert len(p.certifications) == 1
    c = p.certifications[0]
    assert c.name == "Certificate in Calculus"
    assert c.issuing_organization == "Somerville"
    assert c.credential_id == "CALC-1837"
    assert c.issue_date == "03/1837"


def test_languages():
    p = parse()
    langs = {lang.name: lang.proficiency for lang in p.languages}
    assert langs == {
        "English": "NATIVE_OR_BILINGUAL",
        "French": "PROFESSIONAL_WORKING",
    }


def test_empty_response_degrades_with_warnings_not_crash():
    p = parse_profile_view({"included": []}, URL, TS)
    assert p.name is None
    assert p.experience == []
    assert p.warnings  # at least one warning recorded
    assert p.profile_url == URL


def test_missing_included_key():
    p = parse_profile_view({}, URL, TS)
    assert p.name is None
    assert p.warnings
