"""
Orchestrates a profile fetch against LinkedIn's current web app.

  1. GET /in/<slug>/                     -> top card (name, headline, location,
                                            current company, followers, degree,
                                            photos, profile-id)   [1 request]
  2. POST rsc-action component x3        -> about / experience / education
                                            [best-effort; may be blocked]

Step 1 is the reliable core. Step 2 adds the detail sections when the
session survives the extra calls; if a card call is blocked the section
comes back empty with a warning rather than failing the whole request.
Disable step 2 entirely with FETCH_DETAIL_CARDS=0.
"""

import logging
from datetime import datetime, timezone

from .flight_parser import (
    is_self_view,
    parse_about,
    parse_education,
    parse_experience,
    split_date_range,
)
from .models import Education, Experience, LinkedInProfile, ProfileImages
from .page_parser import parse_top_card
from .voyager_client import (
    SessionExpiredError,
    VoyagerRateLimitedError,
    extract_public_identifier,
)
from .web_client import (
    CARD_ABOUT,
    CARD_EDU_SKILLS,
    CARD_EXPERIENCE,
    FETCH_DETAIL_CARDS,
    WebClient,
)

logger = logging.getLogger("linkedin_api.scraper")


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
    flights: list[str] = []

    profile_id = card.get("profile_id")
    if FETCH_DETAIL_CARDS and profile_id:
        for name, fn in (
            (CARD_ABOUT, "about"),
            (CARD_EXPERIENCE, "experience"),
            (CARD_EDU_SKILLS, "education"),
        ):
            try:
                flight = await client.fetch_component(name, slug, profile_id)
            except (SessionExpiredError, VoyagerRateLimitedError) as e:
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
        skills=[],
        certifications=[],
        languages=[],
        scraped_at=scraped_at,
        warnings=warnings,
    )
