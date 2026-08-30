"""
Shared HTTP foundation for talking to LinkedIn.

- config read from the environment (cookies, proxy, TLS-impersonation target)
- `load_cookies()` — the session cookies + CSRF token, from either the full
  browser `cookie:` header (`LI_COOKIE_STRING`, preferred) or the thin
  `LI_AT_COOKIE` + `LI_JSESSIONID_COOKIE` pair
- `proxies()` — outbound proxy dict for curl_cffi, or None
- `session_was_killed()` — detects LinkedIn's "cookie-delete" block response
- `extract_public_identifier()` — `/in/<slug>/` out of a profile URL
- the typed errors the API maps to HTTP status codes

Requests are made with `curl_cffi` (Chrome TLS/HTTP2 impersonation), never a
browser — see README "Approach".
"""

import os
import re
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

BASE_URL = "https://www.linkedin.com"

# The FULL `cookie:` header copied from a logged-in browser request
# (~15 cookies incl. the PerimeterX `_px3`). Preferred over the thin pair
# below — a request carrying only li_at + JSESSIONID is itself a bot signal.
LI_COOKIE_STRING = os.environ.get("LI_COOKIE_STRING") or None
LI_AT_COOKIE = os.environ.get("LI_AT_COOKIE") or None
LI_JSESSIONID_COOKIE = os.environ.get("LI_JSESSIONID_COOKIE") or None

# Outbound proxy for the LinkedIn calls. LinkedIn scores datacenter IPs
# (Render/Fly/…) as high-risk regardless of how clean the request looks, so
# a cloud deployment needs to egress through a residential/mobile proxy.
# e.g. http://user:pass@gate.example.com:7000 — unset = direct.
OUTBOUND_PROXY = os.environ.get("OUTBOUND_PROXY") or None

# curl_cffi browser profile for the TLS/HTTP2 fingerprint.
IMPERSONATE_TARGET = os.environ.get("IMPERSONATE_TARGET", "chrome136")


class SessionExpiredError(Exception):
    """The configured LinkedIn session cookie is no longer valid / was killed."""


class ProfileNotFoundError(Exception):
    """LinkedIn returned 404 / no profile for the given slug."""


class RateLimitedError(Exception):
    """LinkedIn rate-limited or soft-blocked the request (429 / 999)."""


def proxies() -> Optional[Dict[str, str]]:
    if not OUTBOUND_PROXY:
        return None
    return {"http": OUTBOUND_PROXY, "https": OUTBOUND_PROXY}


def _jsessionid_from_cookie_string(cookie_string: str) -> str:
    m = re.search(r'JSESSIONID=("?)([^;"]+)\1', cookie_string)
    return m.group(2) if m else ""


def load_cookies() -> Tuple[Optional[Dict[str, str]], Optional[str], str]:
    """
    Return (cookie_dict, cookie_header, csrf_token).

    Exactly one of cookie_dict / cookie_header is set: the raw header when
    LI_COOKIE_STRING is given, otherwise a {name: value} dict built from
    LI_AT_COOKIE + LI_JSESSIONID_COOKIE. `csrf_token` is the JSESSIONID
    value with surrounding quotes stripped.
    """
    if LI_COOKIE_STRING:
        return None, LI_COOKIE_STRING, _jsessionid_from_cookie_string(LI_COOKIE_STRING)

    if not LI_AT_COOKIE:
        raise SessionExpiredError(
            "No LinkedIn cookie configured. Set LI_COOKIE_STRING (preferred) "
            "or LI_AT_COOKIE + LI_JSESSIONID_COOKIE. See README."
        )

    cookies = {"li_at": LI_AT_COOKIE}
    csrf = ""
    if LI_JSESSIONID_COOKIE:
        jsid = LI_JSESSIONID_COOKIE
        if not jsid.startswith('"'):
            jsid = f'"{jsid}"'
        cookies["JSESSIONID"] = jsid
        csrf = jsid.strip('"')
    return cookies, None, csrf


def session_was_killed(resp) -> bool:
    """
    LinkedIn's block response: a 3xx to a redirect loop plus a `Set-Cookie`
    that expires li_at ("delete me"). Treat that as a dead session.
    """
    try:
        set_cookies = resp.headers.get_list("set-cookie")
    except AttributeError:  # pragma: no cover - header impl dependent
        one = resp.headers.get("set-cookie", "")
        set_cookies = [one] if one else []
    blob = " ".join(set_cookies)
    return "li_at=delete" in blob or 'li_at="delete' in blob


def extract_public_identifier(profile_url: str) -> str:
    """
    https://www.linkedin.com/in/johndoe-12345/  ->  "johndoe-12345"
    """
    path = urlparse(profile_url).path
    match = re.search(r"/in/([^/]+)/?", path)
    if not match:
        raise ValueError(
            f"Could not find a public identifier in URL: {profile_url!r}. "
            "Expected something like https://www.linkedin.com/in/<slug>/"
        )
    return match.group(1)
