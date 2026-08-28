from pathlib import Path

from app.page_parser import extract_profile_id, parse_top_card

HTML = (Path(__file__).parent / "captures" / "mini_profile.html").read_text()


def test_top_card_core_fields():
    c = parse_top_card(HTML, "ada-lovelace")
    assert c["name"] == "Ada Lovelace"
    assert c["headline"] == "Mathematician | Analytical Engine"
    assert c["location"] == "London, England, United Kingdom"
    assert c["current_company"] == "Analytical Engine Project"
    assert c["followers"] == "1,842"
    assert c["connections"] == "500"
    assert c["connection_degree"] == "3rd"
    assert c["website"] == "https://example.org/ada"


def test_profile_id_and_images():
    c = parse_top_card(HTML, "ada-lovelace")
    assert c["profile_id"] == "ACoAAAADATEST0000000000000000000000000"
    assert extract_profile_id(HTML) == c["profile_id"]
    # largest artifact wins, HTML entities decoded
    assert c["profile_photo_url"].endswith("profile-displayphoto-shrink_800_800/x/0/1?e=1&v=beta&t=bb")
    assert "displaybackgroundimage-shrink_350_1400" in c["background_photo_url"]


def test_name_falls_back_to_title_when_slug_missing():
    c = parse_top_card(HTML)  # no slug -> <title>
    assert c["name"] == "Ada Lovelace"


def test_wrong_slug_does_not_pick_a_stranger():
    # title still wins; blob anchor won't match a bogus slug
    c = parse_top_card(HTML, "someone-else")
    assert c["name"] == "Ada Lovelace"
