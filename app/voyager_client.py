"""
Thin HTTP client for LinkedIn's internal "Voyager" API — the same
undocumented REST.li backend linkedin.com and the LinkedIn mobile apps call.
Reverse-engineered by capturing traffic from a logged-in session
(DevTools -> Network -> filter `voyager`) and probing sibling endpoints.

State of play (verified Aug 2026):

- The old bundled endpoint
  `/voyager/api/identity/profiles/{publicId}/profileView` is **gone**
  (HTTP 410). LinkedIn's website migrated the profile page to Server-Driven
  UI (React Server Components) and no longer calls a single JSON endpoint.

- The data is still reachable through the newer "dash" (Data Access Layer)
  endpoint, which the mobile clients still use:

      GET /voyager/api/identity/dash/profiles
          ?q=memberIdentity
          &memberIdentity=<publicIdentifier or profile-id>
          &decorationId=com.linkedin.voyager.dash.deco
                        .identity.profile.FullProfileWithEntities-<N>

  `decorationId` selects a server-side projection: which nested entities
  (positions, educations, skills, certifications, languages, ...) get
  inlined into the response. The `-<N>` suffix is a version LinkedIn bumps
  periodically; `PROFILE_DECORATION_ID` below is the one confirmed working.
  If it starts 4xx-ing, try adjacent versions (`-92`, `-94`, ...) or
  re-capture from a live session.

- Auth is the `li_at` session cookie (see auth.py). Voyager also wants a
  `csrf-token` header whose value is the `JSESSIONID` cookie with the
  surrounding quotes stripped.

- The response follows the REST.li "included" convention: a flat list of
  typed entities (`$type`), cross-referenced by URN, rather than one nested
  document. parser.py stitches them back together.

- LinkedIn actively flags bursts of unusual requests: it replies 302 to a
  redirect loop *and* sends `set-cookie: li_at=delete me` to kill the
  session. `_get` detects that and raises SessionExpiredError. Keep request
  volume low.
"""

import logging
import os
import re
from typing import Any, Dict
from urllib.parse import urlparse

import httpx

from .auth import load_session_cookies

logger = logging.getLogger("linkedin_api.voyager")

BASE_URL = "https://www.linkedin.com"

# Outbound proxy for the LinkedIn calls. LinkedIn flags datacenter IPs
# (Render/Fly/etc.) fast — a deployed instance needs to egress through a
# residential/mobile proxy or it gets its session killed within a request
# or two. Set OUTBOUND_PROXY to a full proxy URL, e.g.
#   http://user:pass@gate.smartproxy.com:7000
# Left unset, requests go direct (fine for local runs from a home IP).
OUTBOUND_PROXY = os.environ.get("OUTBOUND_PROXY") or None

PROFILE_PATH = "/voyager/api/identity/dash/profiles"
PROFILE_DECORATION_ID = (
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93"
)

# Mimic a real browser's client hints; Voyager rejects requests that look
# obviously non-browser (missing these headers, or a generic UA, is one of
# the more common causes of an unexplained 999/403).
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
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


def _session_was_killed(resp: httpx.Response) -> bool:
    """
    LinkedIn's block response: 3xx to a redirect loop plus a Set-Cookie that
    expires li_at ("delete me"). Treat that as a dead session, not a redirect.
    """
    set_cookie = resp.headers.get("set-cookie", "")
    return "li_at=delete" in set_cookie or 'li_at="delete' in set_cookie


class VoyagerClient:
    def __init__(self):
        self._cookie_dict = load_session_cookies()
        csrf_source = self._cookie_dict.get("JSESSIONID", "").strip('"')
        self._headers = dict(DEFAULT_HEADERS)
        if csrf_source:
            self._headers["csrf-token"] = csrf_source

    async def _get(self, path: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        url = f"{BASE_URL}{path}"
        async with httpx.AsyncClient(
            cookies=self._cookie_dict, headers=self._headers, timeout=30.0,
            follow_redirects=False, proxy=OUTBOUND_PROXY,
        ) as client:
            resp = await client.get(url, params=params)

        if _session_was_killed(resp):
            raise SessionExpiredError(
                "LinkedIn killed the session (cookie-delete redirect) — the "
                "request pattern was flagged, or li_at is invalid. Get a "
                "fresh li_at + JSESSIONID and reduce request volume."
            )
        # A plain redirect to the auth wall is the older expiry signal.
        if resp.status_code in (301, 302, 303):
            loc = resp.headers.get("location", "")
            if "authwall" in loc or "/login" in loc or "checkpoint" in loc:
                raise SessionExpiredError(
                    "LinkedIn redirected to the auth wall — the session "
                    "cookie is expired or invalid. Refresh LI_AT_COOKIE."
                )
            raise SessionExpiredError(
                f"Unexpected redirect ({resp.status_code}) to {loc!r} — "
                "session is likely flagged or expired."
            )
        if resp.status_code == 404:
            raise ProfileNotFoundError(f"No profile found for path: {path}")
        if resp.status_code in (429, 999):
            raise VoyagerRateLimitedError(
                "LinkedIn rate-limited or soft-blocked this request "
                f"(status {resp.status_code}). Back off and retry later."
            )
        if resp.status_code in (401, 403):
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

    async def get_profile(self, public_identifier: str) -> Dict[str, Any]:
        """
        Fetch the full profile projection (summary + positions, educations,
        skills, certifications, languages) as one REST.li `included` list.

        `public_identifier` is the `/in/<slug>` value; the profile-id form
        (`ACoAAA...`) also works as `memberIdentity`.
        """
        params = {
            "q": "memberIdentity",
            "memberIdentity": public_identifier,
            "decorationId": PROFILE_DECORATION_ID,
        }
        return await self._get(PROFILE_PATH, params=params)
