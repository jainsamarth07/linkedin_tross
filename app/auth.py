"""
Session handling for the LinkedIn scraper.

We deliberately avoid automating LinkedIn's login form (username + password)
with a headless browser. Doing that reliably trips LinkedIn's bot defenses
(CAPTCHA / email or phone verification "checkpoints") because it looks like a
credential-stuffing attempt from an unrecognized device.

Instead we reuse an already-authenticated browser session by lifting the
`li_at` session cookie (and a couple of supporting cookies) out of a real,
manually-logged-in browser and replaying it on the httpx client that calls
Voyager (see voyager_client.py). This is the same mechanism most LinkedIn
scraping tools use under the hood. The cookie is read from an environment
variable at runtime and is never written into the repository.

`load_session_cookies()` returns a browser-cookie-style list of dicts (the
generic representation); voyager_client.py flattens it to the name->value
mapping httpx wants.

How to obtain the cookie (do this with your own account, see README):
1. Log into linkedin.com normally in Chrome/Firefox.
2. Open DevTools -> Application -> Cookies -> https://www.linkedin.com
3. Copy the value of the `li_at` cookie (and `JSESSIONID` if you want to be
   extra safe against session invalidation) into your `.env` file.
"""

import os
from typing import List, Dict


LINKEDIN_DOMAIN = ".linkedin.com"


def _cookie(name: str, value: str) -> Dict:
    return {
        "name": name,
        "value": value,
        "domain": LINKEDIN_DOMAIN,
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "sameSite": "None",
    }


def load_session_cookies() -> List[Dict]:
    """
    Build the cookie list Playwright needs to treat requests as an
    authenticated session, sourced entirely from environment variables.
    """
    li_at = os.environ.get("LI_AT_COOKIE")
    if not li_at:
        raise RuntimeError(
            "LI_AT_COOKIE environment variable is not set. See README.md "
            "for how to obtain and configure your LinkedIn session cookie."
        )

    cookies = [_cookie("li_at", li_at)]

    jsessionid = os.environ.get("LI_JSESSIONID_COOKIE")
    if jsessionid:
        # LinkedIn wraps this value in literal quotes in the browser; keep
        # that if the user copied it verbatim.
        if not jsessionid.startswith('"'):
            jsessionid = f'"{jsessionid}"'
        cookies.append(_cookie("JSESSIONID", jsessionid))

    return cookies
