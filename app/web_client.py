"""
Client for LinkedIn's current web app ("flagship-web" / COMO / RSC).

Two calls, both endpoints the live site itself uses (so the requests blend
into normal page traffic):

  fetch_profile_html(slug)              GET  /in/<slug>/       -> page HTML (top card)
  fetch_component(component, slug, id)  POST /flagship-web/rsc-action/actions/component
                                                              -> React-Flight text

Auth + TLS impersonation + optional proxy come from linkedin_http. No browser.
"""

import base64
import os
import re
import uuid
from pathlib import Path

from curl_cffi.requests import AsyncSession

from .linkedin_http import (
    BASE_URL,
    IMPERSONATE_TARGET,
    ProfileNotFoundError,
    RateLimitedError,
    SessionExpiredError,
    load_cookies,
    proxies,
    session_was_killed,
)

RSC_ACTION_URL = f"{BASE_URL}/flagship-web/rsc-action/actions/component"
ANCHOR_PAGE_KEY = "d_flagship3_profile_view_base"
COMPONENT_PREFIX = "com.linkedin.sdui.generated.profile.dsl.impl."

# Detail-section components (each returns a small Flight payload).
CARD_ABOUT = "profileCardsAboveActivity"          # -> About
CARD_EXPERIENCE = "profileCardsExperienceOnly"    # -> Experience
CARD_EDUCATION = "profileCardsBelowActivityPart1WithoutExp"   # -> Education
CARD_SKILLS = "profileCardsBelowActivityPart7"    # -> Skills (varies by profile)

_BODY_TPL = (
    Path(__file__).parent / "templates" / "rsc_component_body.json.tpl"
).read_text()

_FLAGSHIP_VER = re.compile(r'"mpName":"flagship-web","mpVersion":"([0-9.]+)"')
_FLAGSHIP_VER_HTML = re.compile(r'mpVersion&quot;:&quot;([0-9.]+)&quot;')
_FALLBACK_FLAGSHIP_VERSION = "0.2.6951"

# The detail cards are extra requests on top of the page load; set to 0 to
# serve the top card only (fewer requests).
FETCH_DETAIL_CARDS = os.environ.get("FETCH_DETAIL_CARDS", "1") not in ("0", "false", "")


def _page_instance() -> str:
    tid = base64.b64encode(uuid.uuid4().bytes).decode()
    return f"urn:li:page:{ANCHOR_PAGE_KEY};{tid}"


class WebClient:
    def __init__(self):
        self._cookie_dict, self._cookie_header, self._csrf = load_cookies()
        self._flagship_version = _FALLBACK_FLAGSHIP_VERSION  # refined from the page HTML

    # curl_cffi takes the cookie jar as `cookies=`; a raw header must go via
    # `headers={"cookie": ...}` instead.
    def _cookie_kw(self):
        if self._cookie_header:
            return {"cookies": None, "extra_headers": {"cookie": self._cookie_header}}
        return {"cookies": self._cookie_dict, "extra_headers": {}}

    def _check(self, resp, what: str):
        if session_was_killed(resp):
            raise SessionExpiredError(
                f"LinkedIn killed the session on {what} (cookie-delete redirect). "
                "Refresh LI_COOKIE_STRING; keep request volume low; from a "
                "datacenter host, try a residential OUTBOUND_PROXY."
            )
        if resp.status_code in (301, 302, 303):
            raise SessionExpiredError(
                f"{what}: unexpected redirect to {resp.headers.get('location')!r}"
            )
        if resp.status_code == 404:
            raise ProfileNotFoundError(f"{what}: 404")
        if resp.status_code in (429, 999):
            raise RateLimitedError(f"{what}: rate-limited ({resp.status_code})")
        if resp.status_code in (401, 403):
            raise SessionExpiredError(f"{what}: {resp.status_code} — session/cookie stale")
        resp.raise_for_status()

    async def fetch_profile_html(self, slug: str) -> str:
        ck = self._cookie_kw()
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            **ck["extra_headers"],
        }
        async with AsyncSession() as s:
            r = await s.get(
                f"{BASE_URL}/in/{slug}/",
                headers=headers,
                cookies=ck["cookies"],
                impersonate=IMPERSONATE_TARGET,
                proxies=proxies(),
                allow_redirects=True,
                timeout=30,
            )
        self._check(r, "profile page")
        html = r.text
        for pat in (_FLAGSHIP_VER, _FLAGSHIP_VER_HTML):
            m = pat.search(html)
            if m:
                self._flagship_version = m.group(1)
                break
        if "authwall" in str(r.url) or "/authwall" in html[:5000]:
            raise SessionExpiredError("profile page: redirected to authwall")
        return html

    async def fetch_component(self, component: str, slug: str, profile_id: str) -> str:
        cid = COMPONENT_PREFIX + component
        body = _BODY_TPL.replace("{VANITY}", slug).replace("{PROFILE_ID}", profile_id or "")
        ck = self._cookie_kw()
        ver = self._flagship_version
        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "origin": BASE_URL,
            "referer": f"{BASE_URL}/in/{slug}/",
            "priority": "u=1, i",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-li-anchor-page-key": ANCHOR_PAGE_KEY,
            "x-li-application-version": ver,
            "x-li-page-instance": _page_instance(),
            "x-li-rsc-stream": "true",
            "x-li-track": (
                '{"clientVersion":"%s","mpVersion":"%s","osName":"web",'
                '"mpName":"flagship-web","deviceFormFactor":"DESKTOP"}' % (ver, ver)
            ),
            **({"csrf-token": self._csrf} if self._csrf else {}),
            **ck["extra_headers"],
        }
        params = {"componentId": cid, "sduiid": cid}
        async with AsyncSession() as s:
            r = await s.post(
                RSC_ACTION_URL,
                params=params,
                data=body,
                headers=headers,
                cookies=ck["cookies"],
                impersonate=IMPERSONATE_TARGET,
                proxies=proxies(),
                allow_redirects=False,
                timeout=30,
            )
        self._check(r, f"card {component}")
        return r.text
