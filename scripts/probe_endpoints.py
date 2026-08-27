"""
Option C probe: does any Voyager profile endpoint still return structured
JSON, now that the website moved to Server-Driven UI?

Reuses the cookie + csrf-token setup from app.voyager_client, then fires a
short list of candidate endpoints against a known profile and reports, for
each: HTTP status, body size, and whether the body actually contains
recognisable profile data.

    python -m scripts.probe_endpoints

Requests are spaced out and the run aborts on the first 429 / 999 to avoid
tripping LinkedIn's soft-block on your session.
"""

import asyncio
import sys
import time

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from app.voyager_client import BASE_URL, VoyagerClient

# williamhgates, lifted from the SDUI payloads in the captured HAR.
SLUG = "williamhgates"
PROFILE_ID = "ACoAAA8BYqEBCGLg_vT_ca6mMEqkpp9nVffJ3hc"
URN = f"urn:li:fsd_profile:{PROFILE_ID}"

DECO = "com.linkedin.voyager.dash.deco.identity.profile"

CANDIDATES = [
    # (label, path, params)
    ("dash/profiles memberIdentity=slug FullProfileWithEntities-93",
     "/voyager/api/identity/dash/profiles",
     {"q": "memberIdentity", "memberIdentity": SLUG,
      "decorationId": f"{DECO}.FullProfileWithEntities-93"}),

    ("dash/profiles memberIdentity=id FullProfileWithEntities-93",
     "/voyager/api/identity/dash/profiles",
     {"q": "memberIdentity", "memberIdentity": PROFILE_ID,
      "decorationId": f"{DECO}.FullProfileWithEntities-93"}),

    ("dash/profiles memberIdentity=slug FullProfileWithEntities-101",
     "/voyager/api/identity/dash/profiles",
     {"q": "memberIdentity", "memberIdentity": SLUG,
      "decorationId": f"{DECO}.FullProfileWithEntities-101"}),

    ("dash/profiles memberIdentity=slug FullProfileWithEntities-70",
     "/voyager/api/identity/dash/profiles",
     {"q": "memberIdentity", "memberIdentity": SLUG,
      "decorationId": f"{DECO}.FullProfileWithEntities-70"}),

    ("dash/profiles memberIdentity=slug (no deco)",
     "/voyager/api/identity/dash/profiles",
     {"q": "memberIdentity", "memberIdentity": SLUG}),

    ("dash/profiles by-urn single-get",
     f"/voyager/api/identity/dash/profiles/{URN}",
     {"decorationId": f"{DECO}.FullProfileWithEntities-93"}),

    ("identity/profiles/{slug} (no profileView suffix)",
     f"/voyager/api/identity/profiles/{SLUG}",
     None),

    ("identity/profiles/{slug}/profileView (known-dead baseline)",
     f"/voyager/api/identity/profiles/{SLUG}/profileView",
     None),

    ("identity/dash/profileCards q=universalName",
     "/voyager/api/identity/dash/profileCards",
     {"q": "universalName", "universalName": SLUG}),

    ("graphql voyagerIdentityDashProfiles (confirmed-working baseline)",
     "/voyager/api/graphql",
     {"includeWebMetadata": "true",
      "variables": f"(memberIdentity:{PROFILE_ID})",
      "queryId": "voyagerIdentityDashProfiles.b5c27c04968c409fc0ed3546575b9b7a"}),
]

DATA_MARKERS = ("firstName", "Microsoft", "Gates", "headline", "Harvard",
                "geo", "multiLocaleFirstName", "profilePicture")


async def main() -> None:
    vc = VoyagerClient()
    headers = dict(vc._headers)
    headers["accept"] = "application/vnd.linkedin.normalized+json+2.1"
    if "csrf-token" not in headers:
        print("WARNING: no csrf-token (LI_JSESSIONID_COOKIE unset) — many "
              "endpoints will 403.\n")

    async with httpx.AsyncClient(cookies=vc._cookie_dict, headers=headers,
                                 timeout=25.0, follow_redirects=False) as client:
        for label, path, params in CANDIDATES:
            url = f"{BASE_URL}{path}"
            try:
                r = await client.get(url, params=params)
            except Exception as e:  # noqa: BLE001
                print(f"[ERR ] {label}\n       {type(e).__name__}: {e}\n")
                continue

            body = r.text
            hit = [m for m in DATA_MARKERS if m in body]
            verdict = "DATA!" if hit else ("empty-ok" if r.status_code == 200 else "-")
            print(f"[{r.status_code:>3}] {label}")
            print(f"       size={len(body):>7}  markers={hit}  {verdict}")
            if r.status_code == 200 and hit:
                snippet = body[:400].replace("\n", " ")
                print(f"       {snippet}")
            if r.status_code in (429, 999):
                print("\nABORT: LinkedIn soft-block hit. Stop and back off.")
                sys.exit(2)
            print()
            time.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
