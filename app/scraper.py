import logging
from datetime import datetime, timezone

from .parser import parse_profile
from .voyager_client import VoyagerClient, extract_public_identifier

logger = logging.getLogger("linkedin_api.scraper")


async def scrape_profile(profile_url: str):
    """
    Full pipeline: URL -> publicIdentifier -> Voyager call -> parsed profile.
    Raises the exceptions defined in voyager_client (SessionExpiredError,
    ProfileNotFoundError, VoyagerRateLimitedError) or ValueError for a
    malformed URL — main.py maps these to HTTP status codes.
    """
    public_id = extract_public_identifier(profile_url)
    client = VoyagerClient()
    raw = await client.get_profile(public_id)
    scraped_at = datetime.now(timezone.utc).isoformat()
    return parse_profile(raw, profile_url, scraped_at)
