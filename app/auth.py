"""
Session handling for the LinkedIn client.

Auth is a session cookie copied once, by hand, from a real browser login —
there is no login automation and no browser anywhere in this project. The
`li_at` cookie (and `JSESSIONID`, used to derive the csrf-token header) are
read from environment variables at runtime and never written into the repo.

How to obtain them (see README for screenshots):
1. Log into linkedin.com normally in Chrome/Firefox (a throwaway account).
2. DevTools -> Application -> Cookies -> https://www.linkedin.com
3. Copy `li_at` -> LI_AT_COOKIE and `JSESSIONID` -> LI_JSESSIONID_COOKIE
   into your `.env`. Grab both in the same sitting (same session).
"""

import os
from typing import Dict


def load_session_cookies() -> Dict[str, str]:
    """
    Return the LinkedIn auth cookies as a plain {name: value} mapping,
    sourced entirely from environment variables. This is exactly what
    httpx.AsyncClient(cookies=...) wants.

    Raises RuntimeError if LI_AT_COOKIE is missing.
    """
    li_at = os.environ.get("LI_AT_COOKIE")
    if not li_at:
        raise RuntimeError(
            "LI_AT_COOKIE environment variable is not set. See README.md "
            "for how to obtain and configure your LinkedIn session cookie."
        )

    cookies = {"li_at": li_at}

    jsessionid = os.environ.get("LI_JSESSIONID_COOKIE")
    if jsessionid:
        # LinkedIn stores this value wrapped in literal double quotes; keep
        # them if the user copied it verbatim, add them if not.
        if not jsessionid.startswith('"'):
            jsessionid = f'"{jsessionid}"'
        cookies["JSESSIONID"] = jsessionid

    return cookies
