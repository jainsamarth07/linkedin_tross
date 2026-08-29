"""
Minimal parser for the React Server Components "Flight" payloads LinkedIn's
current web app (internally "COMO") uses.

Two places produce these:
  1. the `<script id="rehydrate-data">` blob in the profile page HTML
     (`window.__como_rehydration__ = [ "<rows>", ... ]`) — JS-escaped;
  2. the `rsc-action/actions/component` POST responses — raw.

A payload is newline-separated rows `<hexid>:<json-ish>`. The rendered UI
tree lives in rows like `["$","p",null,{"children":["<text>"]}]`. We do not
reconstruct the tree — we pull the **ordered list of visible text leaves**,
which is enough to read a profile card when combined with the section
landmarks ("About", "Experience", "Education", ...).
"""

import re
from typing import List, Optional

_UNESCAPE = [("\\n", "\n"), ('\\"', '"'), ("\\/", "/"), ("\\\\", "\\")]

# "children":["some text"]   and   "children":"some text"
_LEAF_ARRAY = re.compile(r'"children":\[((?:"(?:[^"\\]|\\.)*"(?:,)?)+)\]')
_LEAF_STR = re.compile(r'"children":"((?:[^"\\]|\\.)*)"')
_STR_ITEM = re.compile(r'"((?:[^"\\]|\\.)*)"')


def unescape(blob: str) -> str:
    """Turn a JS-escaped rehydration string into plain Flight text."""
    if '\\"' not in blob and "\\n" not in blob:
        return blob
    out = blob
    for a, b in _UNESCAPE:
        out = out.replace(a, b)
    return out


def _clean(s: str) -> str:
    s = s.replace('\\"', '"').replace("\\/", "/").replace("\\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def text_leaves(blob: str) -> List[str]:
    """
    Ordered visible text from a Flight payload: every string inside a
    `children` position, in document order, de-duplicated only for exact
    adjacent repeats (LinkedIn renders some labels twice).
    """
    blob = unescape(blob)
    hits: List[tuple] = []
    for m in _LEAF_ARRAY.finditer(blob):
        for sm in _STR_ITEM.finditer(m.group(1)):
            hits.append((m.start(), _clean(sm.group(1))))
    for m in _LEAF_STR.finditer(blob):
        hits.append((m.start(), _clean(m.group(1))))
    hits.sort(key=lambda x: x[0])

    out: List[str] = []
    for _, t in hits:
        if not t or t.startswith("$") or t == "·":
            continue
        if out and out[-1] == t:
            continue
        out.append(t)
    return out


def section_after(leaves: List[str], label: str, stop_labels) -> List[str]:
    """
    Text leaves between `label` and the next section label, with UI-chrome /
    self-view / promo leaves removed.
    """
    try:
        start = leaves.index(label) + 1
    except ValueError:
        return []
    stop = set(stop_labels)
    end = start
    while end < len(leaves) and leaves[end] not in stop:
        end += 1
    return [x for x in leaves[start:end] if not _is_junk(x)]


# --- section parsers -------------------------------------------------------

import re as _re

_DATEISH = _re.compile(r"(\b\d{4}\b|Present|Presente|\d+\s*(yr|mo|year|month))", _re.I)
_DURATION = _re.compile(r"\b\d{4}\b.*(?:[–—-]|to|Present|present)", _re.S)
_LOCATIONISH = _re.compile(
    r"\b(Area|Region|Remote|Hybrid|On-site|Metropolitan)\b|^Greater\s|"
    r"United States|United Kingdom|,\s*[A-Z][a-z]+$",
)

# Section headers we split on. Includes the ones that render right after
# Education / Experience in the combined "BelowActivity" card, plus the
# self-view management widgets.
_SECTION_LABELS = (
    "About", "Featured", "Activity", "Experience", "Education", "Skills",
    "Licenses & certifications", "Licenses &amp; certifications",
    "Certifications", "Courses", "Projects", "Publications", "Patents",
    "Honors & awards", "Honors &amp; awards", "Test scores", "Languages",
    "Organizations", "Volunteering", "Volunteer experience", "Causes",
    "Recommendations", "Interests", "Connected apps", "Analytics",
    "Suggested for you", "Private to you", "Post", "Show all",
)

# Leaves that are UI chrome / self-view controls / promos — never data.
_JUNK_LEAF = _re.compile(
    r"^(Add |Show all\b|Show \d|See all\b|Connected apps$|"
    r"Credential ID\b|Issued\b|Skill:|Endorse\b|"
    r"\d[\d,]* (profile views?|post impressions?|search appearances?|"
    r"followers?|connections?|reactions?|comments?)$|"
    r"(Discover|Check out|See how often|Show recruiters) |"
    r"Past \d+ days$|Private to you$|Suggested for you$)",
    _re.I,
)

# " · Full-time", " · Hybrid", " · Remote" etc. tacked onto company/location.
_EMPLOYMENT_SUFFIX = _re.compile(
    r"\s*·\s*(Full-time|Part-time|Self-employed|Freelance|Contract|Internship|"
    r"Apprenticeship|Seasonal|Permanent|Temporary|Hybrid|Remote|On-site)\s*$",
    _re.I,
)


def _is_junk(s: str) -> bool:
    return bool(_JUNK_LEAF.match(s))


def is_self_view(*flights: str) -> bool:
    """
    True if these card payloads are the logged-in user's *own* profile —
    LinkedIn then renders an edit/analytics layout (Add role, Connected apps,
    'N profile views', cert-management rows) that parses poorly. Callers
    should flag this rather than trust the detail sections.
    """
    blob = " ".join(flights)
    markers = ("Add career break", '"Add role"', "Connected apps",
               "profile views", "post impressions", "search appearances",
               "Private to you")
    return sum(m in blob for m in markers) >= 2


def _strip_suffix(s):
    return _EMPLOYMENT_SUFFIX.sub("", s).strip() if s else s


def _is_duration(s: str) -> bool:
    return bool(_DURATION.search(s)) and s not in _SECTION_LABELS


def _is_locationish(s: str) -> bool:
    return bool(_LOCATIONISH.search(s)) and not _is_duration(s)


def parse_about(card_flight: str) -> Optional[str]:
    lv = text_leaves(card_flight)
    if not lv:
        return None
    # first substantial paragraph after "About" (skip section labels / chrome)
    try:
        i = lv.index("About") + 1
    except ValueError:
        return None
    for t in lv[i:i + 5]:
        if t in _SECTION_LABELS or _is_junk(t):
            continue
        if len(t) >= 25:
            return t
    return None


def parse_experience(card_flight: str) -> List[dict]:
    """
    An entry renders as: title, company, duration, [optional location] — with
    the occasional extra line. The **duration** line (a year + '–'/'to'/
    'Present') is the only reliable per-entry anchor, so we buffer leaves and
    flush an entry each time we hit one, taking the last two buffered leaves
    as (title, company). Entries LinkedIn renders without any date are not
    emitted (rare, and guessing them mis-aligns everything after).
    """
    lv = section_after(text_leaves(card_flight), "Experience", _SECTION_LABELS)
    out: List[dict] = []
    buf: List[str] = []
    for k, leaf in enumerate(lv):
        if _is_duration(leaf):
            title = buf[-2] if len(buf) >= 2 else (buf[-1] if buf else None)
            company = _strip_suffix(buf[-1]) if len(buf) >= 2 else None
            location = None
            if k + 1 < len(lv) and _is_locationish(lv[k + 1]):
                location = _strip_suffix(lv[k + 1])
            if title:
                out.append({
                    "title": title, "company": company,
                    "duration": leaf, "location": location,
                })
            buf = []
        elif _is_locationish(leaf) and out and lv[k - 1] == out[-1]["duration"]:
            continue  # already attached as the previous entry's location
        else:
            buf.append(leaf)
    if len(buf) >= 2:  # trailing dateless entry, best effort
        out.append({"title": buf[-2], "company": _strip_suffix(buf[-1]),
                    "duration": None, "location": None})
    return out[:40]


_CERTISH = _re.compile(r"\b(Certified|Certificate|Credential|License|Bootcamp)\b", _re.I)


def parse_education(card_flight: str) -> List[dict]:
    lv = section_after(text_leaves(card_flight), "Education", _SECTION_LABELS)
    out: List[dict] = []
    i = 0
    while i < len(lv):
        school = lv[i]
        i += 1
        duration = degree = None
        while i < len(lv) and lv[i] not in _SECTION_LABELS:
            if _DATEISH.search(lv[i]):
                duration = lv[i]
                i += 1
                break
            if degree is None:
                degree = lv[i]
                i += 1
            else:
                break
        # drop cert rows that leaked in from a section with no header leaf
        # (mostly the self-view "combined" card)
        if school and not (_CERTISH.search(school) and duration is None):
            out.append({"school": school, "degree": degree, "duration": duration})
    return out[:25]


def split_date_range(duration: Optional[str]):
    """
    '2000 – Present'                    -> ('2000', None)
    '1973 – 1975'                       -> ('1973', '1975')
    'Feb 2014 - Present · 12 yrs 7 mos' -> ('Feb 2014', None)
    """
    if not duration:
        return None, None
    d = _re.split(r"\s+·\s+", duration, maxsplit=1)[0]  # drop tenure suffix
    parts = _re.split(r"\s*(?:[–—-]|\bto\b)\s*", d, maxsplit=1)
    start = parts[0].strip() or None
    end = None
    if len(parts) > 1:
        e = parts[1].strip()
        end = None if _re.match(r"(?i)present", e) else (e or None)
    return start, end
