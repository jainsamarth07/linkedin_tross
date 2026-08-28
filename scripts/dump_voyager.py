"""
Dev helper for verifying / debugging the Voyager response shape.

Makes exactly ONE request to the profile endpoint the app uses
(`/voyager/api/identity/dash/profiles`, decorationId FullProfileWithEntities)
using LI_AT_COOKIE / LI_JSESSIONID_COOKIE from your environment / .env, then:

  - detects LinkedIn's session-kill response (302 + `set-cookie: li_at=delete`)
    and aborts loudly instead of looking like a normal redirect;
  - on success, prints every distinct `$type` in `included` (with counts) and
    the top-level keys of the first entity of each type;
  - writes the full response to dash_profile_raw.json (gitignored) for
    offline parser work.

Usage:
    python -m scripts.dump_voyager "https://www.linkedin.com/in/<slug>/"

ONE request per run, on purpose. Bursts of unusual requests get the session
flagged and the cookie invalidated.
"""

import asyncio
import json
import os
import sys
from collections import Counter

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from app.voyager_client import (
    BASE_URL,
    OUTBOUND_PROXY,
    PROFILE_DECORATION_ID,
    PROFILE_PATH,
    VoyagerClient,
    extract_public_identifier,
)

OUT = "dash_profile_raw.json"


async def main(url: str) -> None:
    if not os.environ.get("LI_AT_COOKIE"):
        sys.exit("LI_AT_COOKIE is not set (put it in .env or export it).")

    slug = extract_public_identifier(url)
    vc = VoyagerClient()
    headers = dict(vc._headers)
    headers["accept"] = "application/vnd.linkedin.normalized+json+2.1"
    params = {
        "q": "memberIdentity",
        "memberIdentity": slug,
        "decorationId": PROFILE_DECORATION_ID,
    }

    async with httpx.AsyncClient(
        cookies=vc._cookie_dict, headers=headers, timeout=30.0,
        follow_redirects=False, proxy=OUTBOUND_PROXY,
    ) as client:
        r = await client.get(f"{BASE_URL}{PROFILE_PATH}", params=params)

    print(f"HTTP {r.status_code}  ({len(r.text)} bytes)")

    set_cookie = r.headers.get("set-cookie", "")
    if "li_at=delete" in set_cookie or 'li_at="delete' in set_cookie:
        sys.exit(
            "\nSESSION KILLED: LinkedIn returned a cookie-delete redirect — "
            "the li_at cookie is now invalid. Get a fresh li_at + JSESSIONID "
            "(secondary account recommended) and wait before retrying."
        )
    if r.status_code in (301, 302, 303):
        sys.exit(f"\nUnexpected redirect to: {r.headers.get('location')!r}")
    if r.status_code in (429, 999):
        sys.exit("\nRate-limited / soft-blocked. Back off for a while.")
    r.raise_for_status()

    raw = r.json()
    with open(OUT, "w") as fh:
        json.dump(raw, fh, indent=2)

    included = raw.get("included", [])
    print(f"\nincluded entities: {len(included)}  (full body -> {OUT})\n")

    types = Counter(e.get("$type", "<none>") for e in included)
    print("$type breakdown:")
    for t, n in types.most_common():
        print(f"  {n:3d}  {t}")

    print("\nfirst-of-each-type top-level keys:")
    seen = set()
    for e in included:
        t = e.get("$type", "")
        if t in seen:
            continue
        seen.add(t)
        print(f"\n  {t}")
        print("   ", sorted(e.keys()))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m scripts.dump_voyager <linkedin_profile_url>")
    asyncio.run(main(sys.argv[1]))
