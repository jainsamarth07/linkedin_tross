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
    """Text leaves that fall between `label` and the next known section label."""
    try:
        start = leaves.index(label) + 1
    except ValueError:
        return []
    stop = set(stop_labels)
    end = start
    while end < len(leaves) and leaves[end] not in stop:
        end += 1
    return leaves[start:end]


# --- section parsers -------------------------------------------------------

import re as _re

_DATEISH = _re.compile(r"(\b\d{4}\b|Present|Presente|\d+\s*(yr|mo|year|month))", _re.I)
_DURATION = _re.compile(r"\b\d{4}\b.*(?:[–—-]|to|Present|present)", _re.S)
_LOCATIONISH = _re.compile(
    r"\b(Area|Region|Remote|Hybrid|On-site|Metropolitan)\b|^Greater\s|"
    r"United States|United Kingdom|,\s*[A-Z][a-z]+$",
)
_SECTION_LABELS = ("About", "Featured", "Activity", "Experience", "Education",
                   "Licenses & certifications", "Skills", "Languages",
                   "Volunteering", "Post", "Show all")


def _is_duration(s: str) -> bool:
    return bool(_DURATION.search(s)) and s not in _SECTION_LABELS


def _is_locationish(s: str) -> bool:
    return bool(_LOCATIONISH.search(s)) and not _is_duration(s)


def parse_about(card_flight: str) -> Optional[str]:
    lv = text_leaves(card_flight)
    if not lv:
        return None
    # first substantial paragraph after "About" (skip the "Featured" label)
    try:
        i = lv.index("About") + 1
    except ValueError:
        i = 0
    for t in lv[i:i + 4]:
        if t in _SECTION_LABELS:
            continue
        if len(t) >= 20:
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
            company = buf[-1] if len(buf) >= 2 else None
            location = None
            if k + 1 < len(lv) and _is_locationish(lv[k + 1]):
                location = lv[k + 1]
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
        out.append({"title": buf[-2], "company": buf[-1],
                    "duration": None, "location": None})
    return out


def parse_education(card_flight: str) -> List[dict]:
    lv = section_after(text_leaves(card_flight), "Education", _SECTION_LABELS)
    out: List[dict] = []
    i = 0
    while i < len(lv):
        school = lv[i]
        i += 1
        duration = degree = None
        # optional following lines: degree/field, then a date range
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
        if school:
            out.append({"school": school, "degree": degree, "duration": duration})
    return out


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
