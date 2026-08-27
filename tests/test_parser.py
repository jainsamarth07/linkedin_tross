from app.parser import parse_profile
from tests.fixtures import MOCK_DASH_PROFILE

URL = "https://www.linkedin.com/in/ada-lovelace/"
TS = "2026-08-27T00:00:00+00:00"


def parse():
    return parse_profile(MOCK_DASH_PROFILE, URL, TS)


def test_summary_fields():
    p = parse()
    assert p.profile_url == URL
    assert p.name == "Ada Lovelace"
    assert p.headline.startswith("Mathematician")
    assert p.about.startswith("Fascinated")
    assert p.scraped_at == TS


def test_location_resolved_via_geo_urn():
    p = parse()
    assert p.location == "London, England, United Kingdom"


def test_images_pick_largest_artifact():
    p = parse()
    assert p.images.profile_photo_url == "https://media.licdn.com/dms/image/pp/800/a.jpg"
    assert p.images.background_photo_url == (
        "https://media.licdn.com/dms/image/bg/1400/b.jpg"
    )


def test_experience_with_daterange_and_company_ref():
    p = parse()
    assert len(p.experience) == 2
    first = p.experience[0]
    assert first.title == "Collaborator"
    assert first.company == "Analytical Engine Project"
    assert first.start_date == "01/1842"
    assert first.end_date == "12/1843"
    assert first.duration == "01/1842 - 12/1843"
    assert first.company_logo_url == "https://media.licdn.com/dms/image/co/200/c.png"
    # ongoing role -> "Present"; company name only in multiLocale map
    assert p.experience[1].duration == "1843 - Present"
    assert p.experience[1].company == "Self-employed"


def test_education_with_school_ref():
    p = parse()
    assert len(p.education) == 1
    edu = p.education[0]
    assert edu.school == "Private tutoring"
    assert edu.degree == "Mathematics & Science"
    assert edu.field_of_study == "Mathematics"
    assert edu.duration == "1833 - 1840"
    assert edu.school_logo_url == "https://media.licdn.com/dms/image/sc/200/d.png"


def test_skills_certs_languages_empty_with_warning():
    p = parse()
    assert p.skills == []
    assert p.certifications == []
    assert p.languages == []
    assert any("Skills, certifications and languages" in w for w in p.warnings)


def test_empty_response_degrades_not_crash():
    p = parse_profile({"included": []}, URL, TS)
    assert p.name is None
    assert p.experience == []
    assert p.location is None
    assert p.warnings
    assert p.profile_url == URL


def test_missing_included_key():
    p = parse_profile({}, URL, TS)
    assert p.name is None
    assert p.warnings
