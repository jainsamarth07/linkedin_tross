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

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from app.voyager_client import (
    ProfileNotFoundError,
    SessionExpiredError,
    VoyagerClient,
    VoyagerRateLimitedError,
    extract_public_identifier,
)

OUT = "dash_profile_raw.json"


async def main(url: str) -> None:
    if not (os.environ.get("LI_AT_COOKIE") or os.environ.get("LI_COOKIE_STRING")):
        sys.exit("Set LI_AT_COOKIE (or LI_COOKIE_STRING) in .env or the env.")

    slug = extract_public_identifier(url)
    # Reuse the exact production request path (headers, cookies, proxy,
    # impersonation, error handling all identical to the running API).
    try:
        raw = await VoyagerClient().get_profile(slug)
    except SessionExpiredError as e:
        sys.exit(f"\nSESSION KILLED / EXPIRED: {e}")
    except VoyagerRateLimitedError as e:
        sys.exit(f"\nRATE-LIMITED: {e}")
    except ProfileNotFoundError as e:
        sys.exit(f"\nNOT FOUND: {e}")

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
