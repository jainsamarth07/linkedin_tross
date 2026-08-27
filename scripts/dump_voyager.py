"""
Dev helper for the "live verification" step (CLAUDE.md #3).

Once you have a real LI_AT_COOKIE in your environment / .env, run:

    python -m scripts.dump_voyager "https://www.linkedin.com/in/<slug>/"

It calls the real Voyager profileView endpoint and prints:
  - every distinct `$type` in the `included` list (with counts)
  - the top-level keys present on the first Profile / Position / Education /
    Skill / Certification / Language entity

Diff that against the TYPE_* constants and `.get(...)` field names in
app/parser.py and fix any drift.
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

from app.voyager_client import VoyagerClient, extract_public_identifier


async def main(url: str) -> None:
    if not os.environ.get("LI_AT_COOKIE"):
        sys.exit("LI_AT_COOKIE is not set (put it in .env or export it).")

    public_id = extract_public_identifier(url)
    raw = await VoyagerClient().get_profile_view(public_id)
    included = raw.get("included", [])

    print(f"included entities: {len(included)}\n")

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

    dump_path = "voyager_raw.json"
    with open(dump_path, "w") as fh:
        json.dump(raw, fh, indent=2)
    print(f"\nfull response written to {dump_path} (gitignored)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m scripts.dump_voyager <linkedin_profile_url>")
    asyncio.run(main(sys.argv[1]))
