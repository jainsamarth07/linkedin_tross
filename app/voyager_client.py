"""
Thin HTTP client for LinkedIn's internal "Voyager" API — the same
undocumented REST.li backend linkedin.com's own frontend calls when you
browse a profile. Reverse-engineered by inspecting the Network tab while
browsing a profile page while logged in (DevTools -> Network -> filter
`voyager`).

Key facts about this API surface:
- It's authenticated via the `li_at` session cookie (see auth.py).
- Every mutating-looking call (even some GETs) requires a CSRF token sent
  as the `csrf-token` header, whose value is the `JSESSIONID` cookie value
  (LinkedIn re-uses the session id as the CSRF token).
- Responses follow the REST.li "included" pattern: instead of one nested
  JSON tree, entities (Profile, Position, Education, Skill, Certification,
  Language...) are returned as a flat list, each tagged with a `$type` and
  cross-referenced by URN. The parser (parser.py) is responsible for
  stitching these back together.
- LinkedIn changes field names and endpoint paths periodically. If this
  starts returning unexpected shapes, re-capture the request from a live
  browser session (DevTools Network tab) and diff against what's here.
"""

import logging
import re
from typing import Any, Dict
from urllib.parse import urlparse

import httpx

from .auth import load_session_cookies

logger = logging.getLogger("linkedin_api.voyager")

BASE_URL = "https://www.linkedin.com"

# Mimic a real browser's client hints; Voyager rejects requests that look
# obviously non-browser (missing these headers, or a generic UA, is one of
# the more common causes of an unexplained 999/403).
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/vnd.linkedin.normalized+json+2.1",
    "x-restli-protocol-version": "2.0.0",
    "x-li-lang": "en_US",
    "x-li-track": '{"clientVersion":"1.13.0","mpVersion":"1.13.0","osName":"web"}',
}


class SessionExpiredError(Exception):
    """Raised when the configured li_at cookie is no longer valid."""


class ProfileNotFoundError(Exception):
    """Raised when LinkedIn returns a 404 / empty result for the profile."""


class VoyagerRateLimitedError(Exception):
    """Raised on 429 or LinkedIn's soft-block (999) responses."""


def extract_public_identifier(profile_url: str) -> str:
    """
    Pull the publicIdentifier out of a profile URL, e.g.
    https://www.linkedin.com/in/johndoe-12345/ -> "johndoe-12345"
    """
    path = urlparse(profile_url).path
    match = re.search(r"/in/([^/]+)/?", path)
    if not match:
        raise ValueError(
            f"Could not find a public identifier in URL: {profile_url!r}. "
            "Expected something like https://www.linkedin.com/in/<slug>/"
        )
    return match.group(1)


class VoyagerClient:
    def __init__(self):
        self._cookies = load_session_cookies()
        # httpx wants a plain name->value cookie dict for requests, not the
        # Playwright-style dict list we use elsewhere (auth.py is shared
        # infra for both a browser-based and an httpx-based path).
        self._cookie_dict = {c["name"]: c["value"] for c in self._cookies}
        csrf_source = self._cookie_dict.get("JSESSIONID", "").strip('"')
        self._headers = dict(DEFAULT_HEADERS)
        if csrf_source:
            self._headers["csrf-token"] = csrf_source

    async def _get(self, path: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        url = f"{BASE_URL}{path}"
        async with httpx.AsyncClient(
            cookies=self._cookie_dict, headers=self._headers, timeout=20.0,
            follow_redirects=False,
        ) as client:
            resp = await client.get(url, params=params)

        # LinkedIn signals a dead/invalid session by redirecting to the
        # login wall rather than returning a clean 401.
        if resp.status_code in (301, 302, 303) and "authwall" in resp.headers.get(
            "location", ""
        ):
            raise SessionExpiredError(
                "LinkedIn redirected to the auth wall — the session cookie "
                "is expired or invalid. Refresh LI_AT_COOKIE."
            )
        if resp.status_code == 404:
            raise ProfileNotFoundError(f"No profile found for path: {path}")
        if resp.status_code == 999 or resp.status_code == 429:
            raise VoyagerRateLimitedError(
                "LinkedIn rate-limited or soft-blocked this request "
                f"(status {resp.status_code}). Back off and retry later."
            )
        if resp.status_code == 401 or resp.status_code == 403:
            raise SessionExpiredError(
                f"Voyager returned {resp.status_code} — session cookie is "
                "likely expired, or the csrf-token header is stale/missing."
            )
        resp.raise_for_status()

        try:
            return resp.json()
        except ValueError:
            logger.error("Non-JSON Voyager response for %s: %s", path, resp.text[:500])
            raise

    async def get_profile_view(self, public_identifier: str) -> Dict[str, Any]:
        """
        Calls the bundled profileView endpoint, which returns the summary
        profile plus positions, education, skills, certifications and
        languages in one response (as a flat `included` entity list).
        """
        path = f"/voyager/api/identity/profiles/{public_identifier}/profileView"
        return await self._get(path)
