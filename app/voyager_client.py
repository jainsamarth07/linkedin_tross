"""
HTTP client for LinkedIn's internal "Voyager" API — the same undocumented
REST.li backend linkedin.com and the LinkedIn mobile apps call.
Reverse-engineered by capturing traffic from a logged-in session
(DevTools -> Network -> filter `voyager`) and probing sibling endpoints.
Built on `curl_cffi` (not httpx/requests) so the TLS + HTTP2 fingerprint
impersonates real Chrome — see the fingerprint note below.

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

- TLS/HTTP2 fingerprint matters. A plain Python HTTP client (httpx/requests)
  has a JA3/JA4 + HTTP2-SETTINGS fingerprint that doesn't match any browser,
  which is itself a bot signal regardless of headers. We use `curl_cffi`
  with `impersonate=` so the handshake matches real Chrome. This does NOT
  fix a datacenter IP — pair it with OUTBOUND_PROXY.
"""

import base64
import logging
import os
import re
import uuid
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession

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

# Browser to impersonate at the TLS/HTTP2 layer (curl_cffi target name).
# Keep it consistent with the User-Agent string in DEFAULT_HEADERS. Bump
# both together when Chrome moves on.
IMPERSONATE_TARGET = os.environ.get("IMPERSONATE_TARGET", "chrome136")

# Optional: the FULL `cookie:` header copied verbatim from a real logged-in
# browser request (DevTools -> Network -> a `voyager` request -> Copy ->
# Copy as cURL -> the `-H 'cookie: ...'` value). A real session carries
# ~15 cookies (bcookie, bscookie, lidc, liap, li_gc, ...); sending only
# li_at + JSESSIONID is itself a bot signal. When set, this is used as-is
# and LI_AT_COOKIE / LI_JSESSIONID_COOKIE are ignored for the Cookie header
# (JSESSIONID is still parsed out of it for the csrf-token).
LI_COOKIE_STRING = os.environ.get("LI_COOKIE_STRING") or None

# Real clientVersion from a captured request. LinkedIn can tell a made-up
# version from a shipped one; override via LI_CLIENT_VERSION when it drifts.
LI_CLIENT_VERSION = os.environ.get("LI_CLIENT_VERSION", "1.13.46243")


def _proxies() -> Optional[Dict[str, str]]:
    if not OUTBOUND_PROXY:
        return None
    return {"http": OUTBOUND_PROXY, "https": OUTBOUND_PROXY}

PROFILE_PATH = "/voyager/api/identity/dash/profiles"
PROFILE_DECORATION_ID = (
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93"
)

# Header set mirrored from a real captured `voyager` request. The
# User-Agent / sec-ch-ua / accept-encoding are left to curl_cffi's
# `impersonate=` so they stay internally consistent with the TLS profile.
# A request missing `referer` / `sec-fetch-*` / a real `x-li-track`
# clientVersion looks non-browser and is a common cause of an unexplained
# 999 / session kill.
def _x_li_track() -> str:
    return (
        '{"clientVersion":"%s","mpVersion":"%s","osName":"web",'
        '"timezoneOffset":0,"timezone":"UTC","deviceFormFactor":"DESKTOP",'
        '"mpName":"voyager-web","displayDensity":2,"displayWidth":2560,'
        '"displayHeight":1440}' % (LI_CLIENT_VERSION, LI_CLIENT_VERSION)
    )


def _x_li_page_instance() -> str:
    tid = base64.b64encode(uuid.uuid4().bytes).decode()
    return f"urn:li:page:d_flagship3_profile_view_base;{tid}"


DEFAULT_HEADERS = {
    "accept": "application/vnd.linkedin.normalized+json+2.1",
    "accept-language": "en-US,en;q=0.9",
    "x-restli-protocol-version": "2.0.0",
    "x-li-lang": "en_US",
    "x-li-track": _x_li_track(),
    "priority": "u=1, i",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
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


def _session_was_killed(resp) -> bool:
    """
    LinkedIn's block response: 3xx to a redirect loop plus a Set-Cookie that
    expires li_at ("delete me"). Treat that as a dead session, not a redirect.
    """
    headers = resp.headers
    try:
        set_cookies = headers.get_list("set-cookie")
    except AttributeError:  # pragma: no cover - depends on header impl
        one = headers.get("set-cookie", "")
        set_cookies = [one] if one else []
    blob = " ".join(set_cookies)
    return "li_at=delete" in blob or 'li_at="delete' in blob


def _jsessionid_from_cookie_string(cookie_string: str) -> str:
    m = re.search(r'JSESSIONID=("?)([^;"]+)\1', cookie_string)
    return m.group(2) if m else ""


class VoyagerClient:
    def __init__(self):
        self._headers = dict(DEFAULT_HEADERS)

        if LI_COOKIE_STRING:
            # Replay a full real browser cookie header verbatim.
            self._cookie_dict = None
            self._cookie_header = LI_COOKIE_STRING
            csrf_source = _jsessionid_from_cookie_string(LI_COOKIE_STRING)
        else:
            self._cookie_dict = load_session_cookies()
            self._cookie_header = None
            csrf_source = self._cookie_dict.get("JSESSIONID", "").strip('"')

        if csrf_source:
            self._headers["csrf-token"] = csrf_source

    async def _get(self, path: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        url = f"{BASE_URL}{path}"
        headers = dict(self._headers)
        headers["x-li-page-instance"] = _x_li_page_instance()
        headers["referer"] = "https://www.linkedin.com/feed/"
        if self._cookie_header:
            headers["cookie"] = self._cookie_header

        async with AsyncSession() as session:
            resp = await session.get(
                url,
                params=params,
                headers=headers,
                cookies=self._cookie_dict,
                impersonate=IMPERSONATE_TARGET,
                proxies=_proxies(),
                allow_redirects=False,
                timeout=30,
            )

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
