"""
Orchestrates a profile fetch against LinkedIn's current web app.

  1. GET /in/<slug>/                 -> top card (name, headline, location,
                                        current company, followers, degree,
                                        photos, profile-id)          [1 request]
  2. POST rsc-action component x4    -> about / experience / education / skills
                                        [best-effort; may be blocked]

Step 1 is the reliable core. Step 2 adds the detail sections when the session
survives the extra calls; a blocked card yields an empty section + a warning,
not a failed request. Disable step 2 with FETCH_DETAIL_CARDS=0.
"""

from datetime import datetime, timezone

from .flight_parser import (
    is_self_view,
    parse_about,
    parse_education,
    parse_experience,
    parse_skills,
    split_date_range,
)
from .linkedin_http import (
    RateLimitedError,
    SessionExpiredError,
    extract_public_identifier,
)
from .models import Education, Experience, LinkedInProfile, ProfileImages, Skill
from .page_parser import parse_top_card
from .web_client import (
    CARD_ABOUT,
    CARD_EDUCATION,
    CARD_EXPERIENCE,
    CARD_SKILLS,
    FETCH_DETAIL_CARDS,
    WebClient,
)


async def scrape_profile(profile_url: str) -> LinkedInProfile:
    slug = extract_public_identifier(profile_url)
    client = WebClient()
    scraped_at = datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []

    html = await client.fetch_profile_html(slug)
    card = parse_top_card(html, slug)
    if not card.get("name"):
        warnings.append(
            "Could not read the top card from the profile page — the page "
            "markup may have changed, or the profile is not visible to this "
            "session."
        )

    about = None
    experience: list[Experience] = []
    education: list[Education] = []
    skills: list[Skill] = []
    flights: list[str] = []

    profile_id = card.get("profile_id")
    if FETCH_DETAIL_CARDS and profile_id:
        for name, fn in (
            (CARD_ABOUT, "about"),
            (CARD_EXPERIENCE, "experience"),
            (CARD_EDUCATION, "education"),
            (CARD_SKILLS, "skills"),
        ):
            try:
                flight = await client.fetch_component(name, slug, profile_id)
            except (SessionExpiredError, RateLimitedError) as e:
                warnings.append(
                    f"Detail section '{fn}' unavailable: {type(e).__name__}. "
                    "Top-card data above is still valid."
                )
                break
            except Exception as e:  # noqa: BLE001
                warnings.append(f"Detail section '{fn}' failed to parse: {e}")
                continue

            flights.append(flight)
            if fn == "about":
                about = parse_about(flight)
            elif fn == "experience":
                for x in parse_experience(flight):
                    s, en = split_date_range(x["duration"])
                    experience.append(
                        Experience(
                            title=x["title"], company=x["company"],
                            duration=x["duration"], start_date=s, end_date=en,
                            location=x.get("location"),
                        )
                    )
            elif fn == "education":
                for x in parse_education(flight):
                    s, en = split_date_range(x["duration"])
                    education.append(
                        Education(
                            school=x["school"], degree=x["degree"],
                            duration=x["duration"], start_date=s, end_date=en,
                        )
                    )
            elif fn == "skills":
                for x in parse_skills(flight):
                    skills.append(
                        Skill(name=x["name"],
                              endorsement_count=x["endorsement_count"])
                    )
        if is_self_view(*flights):
            warnings.append(
                "This is the logged-in user's OWN profile — LinkedIn serves an "
                "edit/analytics layout, so about/experience/education are "
                "partial and may be imperfect. Scrape it with a different "
                "account's cookie for clean data."
            )
    elif not FETCH_DETAIL_CARDS:
        warnings.append("Detail sections disabled (FETCH_DETAIL_CARDS=0).")
    elif not profile_id:
        warnings.append("No profile id in page HTML — detail sections skipped.")

    return LinkedInProfile(
        profile_url=profile_url,
        name=card.get("name"),
        headline=card.get("headline"),
        location=card.get("location"),
        current_company=card.get("current_company"),
        about=about,
        connections=card.get("connections"),
        connection_degree=card.get("connection_degree"),
        followers=card.get("followers"),
        website=card.get("website"),
        images=ProfileImages(
            profile_photo_url=card.get("profile_photo_url"),
            background_photo_url=card.get("background_photo_url"),
        ),
        experience=experience,
        education=education,
        skills=skills,
        certifications=[],
        languages=[],
        scraped_at=scraped_at,
        warnings=warnings,
    )
