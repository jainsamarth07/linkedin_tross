"""
Parse a logged-in LinkedIn profile page (`GET /in/<slug>/`) into the parts
that are server-rendered in the initial HTML: the **top card**.

LinkedIn's current web app ("COMO") server-renders the top card and embeds
the same data as a React-Flight blob in `<script id="rehydrate-data">`
(`window.__como_rehydration__`). About / Experience / Education are NOT in
this HTML — they load later via `rsc-action` calls (see web_client +
flight_parser). So this module fills name / headline / location / current
company / followers / degree / website / photos / profile-id, and the
scraper layers the detail sections on top when available.

Everything is landmark-anchored (the `<title>`, the `firstName`/`lastName`
JSON, the `"… followers"` / `"Contact info"` leaves, `licdn` image URLs) —
never the hashed CSS class names, which churn.
"""

import html as _html
import re
from typing import Dict, List, Optional

from .flight_parser import text_leaves

_REHYDRATE = re.compile(
    r'<script[^>]*\bid="rehydrate-data"[^>]*>(.*?)</script>', re.S
)
_FIRST = re.compile(r'\\?"firstName\\?":\\?"([^"\\]+)\\?"')
_LAST = re.compile(r'\\?"lastName\\?":\\?"([^"\\]+)\\?"')
_PID = re.compile(r'\\?"vieweeProfileId\\?":\\?"([A-Za-z0-9_-]{10,})\\?"')
_TITLE = re.compile(r"<title>([^<]*)</title>", re.I)
_FOLLOWERS = re.compile(r"([\d,]+)\s+followers?\b")
_CONNECTIONS = re.compile(r"([\d,]+)\+?\s+connections?\b")
_DEGREE = re.compile(r"·\s*(1st|2nd|3rd)\b")
_GEOISH = re.compile(r"^[^·|]+,\s*[^·|]+$")

_JUNK_LEAF = re.compile(
    r"^(More|Connect|Follow|Unfollow|Message|Following|Pending|"
    r"View my newsletter|Contact info|Save to PDF|Send profile in a message|"
    r"Report |Block |About|Featured)"
)


def _biggest_image(html: str, kind: str) -> Optional[str]:
    best, best_w = None, -1
    pat = re.compile(
        r'https://media\.licdn\.com/dms/image/[^\s"\'\\]*'
        + re.escape(kind)
        + r"-shrink_(\d+)_\d+[^\s\"'\\]*"
    )
    for m in pat.finditer(html):
        w = int(m.group(1))
        if w > best_w:
            best_w, best = w, m.group(0)
    return _html.unescape(best) if best else None


def extract_profile_id(html: str) -> Optional[str]:
    m = _REHYDRATE.search(html)
    blob = m.group(1) if m else html
    pm = _PID.search(blob)
    return pm.group(1) if pm else None


def _name(html: str, blob: str, slug: Optional[str] = None) -> Optional[str]:
    # 1) <title> — "Satya Nadella | LinkedIn"  /  "Name - Company | LinkedIn"
    tm = _TITLE.search(html)
    if tm:
        t = _html.unescape(tm.group(1))
        t = re.sub(r"\s*\|\s*LinkedIn\s*$", "", t)
        t = re.split(r"\s[|–—-]\s", t)[0]
        t = re.sub(r"\s+", " ", t).strip()
        if t and t.lower() != "linkedin":
            return t
    # 2) slug-anchored firstName/lastName in the rehydration blob (there are
    #    other people's names in there — pick the block near this vanity)
    if slug:
        for m in re.finditer(
            r'\\?"(?:inviteeVanityName|profileCanonicalUrl)\\?":\\?"[^"\\]*'
            + re.escape(slug)
            + r'[^"\\]*\\?"(.{0,160})',
            blob,
        ):
            seg = m.group(1)
            fm, lm = _FIRST.search(seg), _LAST.search(seg)
            if fm and lm:
                return re.sub(r"\s+", " ", f"{fm.group(1)} {lm.group(1)}").strip()
    # 3) first firstName/lastName anywhere (last resort)
    fm, lm = _FIRST.search(blob), _LAST.search(blob)
    if fm and lm:
        return re.sub(r"\s+", " ", f"{fm.group(1)} {lm.group(1)}").strip()
    return None


def _top_card_lines(blob: str) -> Dict[str, Optional[str]]:
    """
    In the rehydration leaves the card renders as a contiguous run:
        '· 3rd' , <headline> , <current company> , <location> , 'Contact info' , 'N followers'
    Anchor on 'Contact info' (very common) or the degree marker; fall back
    to the leaf before the 'followers' leaf.
    """
    leaves: List[str] = text_leaves(blob)
    res = {"headline": None, "current_company": None, "location": None}
    if not leaves:
        return res

    anchor = None
    for i, lv in enumerate(leaves):
        if lv == "Contact info":
            anchor = i
            break
    if anchor is None:
        for i, lv in enumerate(leaves):
            if _FOLLOWERS.match(lv):
                anchor = i + 1  # treat like Contact-info slot
                break
    if anchor is None:
        for i, lv in enumerate(leaves):
            if _DEGREE.search(lv):
                anchor = i + 4
                break
    if anchor is None:
        return res

    window = [w for w in leaves[max(0, anchor - 3):anchor] if w and not _JUNK_LEAF.match(w)]
    if not window:
        return res

    # location = last geo-ish line in the window
    loc_idx = None
    for j in range(len(window) - 1, -1, -1):
        if _GEOISH.match(window[j]) and not _FOLLOWERS.search(window[j]):
            loc_idx = j
            break
    if loc_idx is not None:
        res["location"] = window[loc_idx]
        if loc_idx - 1 >= 0:
            res["current_company"] = window[loc_idx - 1]
        if loc_idx - 2 >= 0:
            res["headline"] = window[loc_idx - 2]
        elif loc_idx - 1 >= 0 and res["headline"] is None and loc_idx - 1 != loc_idx:
            pass
    else:
        # no clear location; first line is most likely the headline
        res["headline"] = window[0]
        if len(window) > 1:
            res["current_company"] = window[1]
    return res


def parse_top_card(html: str, slug: Optional[str] = None) -> Dict[str, Optional[str]]:
    m = _REHYDRATE.search(html)
    blob = m.group(1) if m else ""

    card = _top_card_lines(blob)
    fol = _FOLLOWERS.search(html)
    con = _CONNECTIONS.search(html)
    deg = _DEGREE.search(html)

    _BADHOST = ("linkedin.com", "licdn.com", "gstatic", "w3.org", "schema.org",
                "g.co/", "microsoft.com/en-us/legal", "static.licdn")
    website = None
    for lv in text_leaves(blob):
        if lv.startswith(("http://", "https://")) and not any(b in lv for b in _BADHOST):
            website = lv
            break

    return {
        "name": _name(html, blob, slug),
        "headline": card["headline"],
        "location": card["location"],
        "current_company": card["current_company"],
        "followers": fol.group(1) if fol else None,
        "connections": con.group(1) if con else None,
        "connection_degree": deg.group(1) if deg else None,
        "website": website,
        "profile_photo_url": _biggest_image(html, "profile-displayphoto"),
        "background_photo_url": _biggest_image(html, "profile-displaybackgroundimage"),
        "profile_id": extract_profile_id(html),
    }
