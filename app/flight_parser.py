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

import json
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
    s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
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

_EMP = (r"Full-time|Part-time|Self-employed|Freelance|Contract|Internship|"
        r"Apprenticeship|Seasonal|Permanent|Temporary")
# " · Full-time", " · Hybrid", " · Remote" etc. tacked onto company/location.
_EMPLOYMENT_SUFFIX = _re.compile(
    rf"\s*·\s*({_EMP}|Hybrid|Remote|On-site)\s*$", _re.I)
# a leaf that is "<Company> · <EmploymentType>" — the standalone-entry marker
_COMPANY_TYPE = _re.compile(rf"^(.+?)\s*·\s*({_EMP})\s*$", _re.I)
# school / degree keywords, to keep real education and drop cert/project rows
_SCHOOL_KW = _re.compile(
    r"\b(University|College|Institute|School|Academy|Polytechnic|"
    r"Universit|Universidad|École|Ecole|Hochschule|IIT|IIM|NIT)\b", _re.I)
_DEGREE_KW = _re.compile(
    r"\b(Bachelor|Master|Doctor|PhD|Ph\.D|B\.?Tech|M\.?Tech|B\.?E\b|M\.?E\b|"
    r"B\.?Sc|M\.?Sc|B\.?A\b|M\.?A\b|MBA|BBA|Diploma|Associate|Postgraduate|"
    r"Undergraduate|Engineering)\b", _re.I)
_EMPLOYMENT_TYPE = frozenset(
    x.lower() for x in (
        "Full-time", "Part-time", "Self-employed", "Freelance", "Contract",
        "Internship", "Apprenticeship", "Seasonal", "Permanent", "Temporary",
    )
)
# a standalone tenure like "3 yrs 7 mos" / "5 mos" — NO year, NO dash. Marks a
# company GROUP header (roles that follow inherit its company name).
_BARE_TENURE = _re.compile(
    r"^\d+\s*(yr|yrs|year|years|mo|mos|month|months)"
    r"(\s+\d+\s*(mo|mos|month|months))?$",
    _re.I,
)


def _is_employment_type(s: str) -> bool:
    return s.lower() in _EMPLOYMENT_TYPE


def _is_bare_tenure(s: str) -> bool:
    return bool(_BARE_TENURE.match(s))


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


# ---------------------------------------------------------------------------
# Experience: a small React-Flight *tree* resolver.
#
# text_leaves() is a flat byte-order scan — good enough for About / Education /
# Skills, but the Experience card puts the role blurbs in lazily-resolved
# component rows (`$L..` refs, expandable-text / bulleted `$2*` nodes) that
# stream out of order relative to their roles. To read descriptions and to get
# grouped roles right we walk the actual component tree in display order and
# tag every text node as HEADER (a <p>: title / company / tenure line),
# DETAIL (a textProps line: date / location) or DESC (an expandable / bulleted
# block: the role description).
# ---------------------------------------------------------------------------

_ROW = re.compile(r"(?m)^([0-9a-f]+):(.*(?:\n(?![0-9a-f]+:).*)*)")
_REF = re.compile(r"^\$L?([0-9a-f]+)$")
_TAGPFX = re.compile(r'^[A-Za-z]+(?=[\[{"])')
_HEADER, _DETAIL, _DESC = "HEADER", "DETAIL", "DESC"


def _load_flight_rows(blob: str) -> dict:
    # raw rsc-action payload — do NOT unescape (it would corrupt the JSON rows)
    rows: dict = {}
    for m in _ROW.finditer(blob):
        rid, val = m.group(1), m.group(2)
        pfx = _TAGPFX.match(val)          # strip a Flight tag letter ("I[...]", "HL[...]")
        if pfx:
            val = val[pfx.end():]
        try:
            rows[rid] = json.loads(val)
        except Exception:
            rows[rid] = None
    return rows


def _is_elem(n) -> bool:
    return isinstance(n, list) and len(n) >= 4 and n[0] == "$"


def _elem_strings(node, rows, seen) -> List[str]:
    """Human text under an element subtree, in order, resolving $L refs."""
    acc: List[str] = []

    def rec(n):
        if isinstance(n, str):
            m = _REF.match(n)
            if m and m.group(1) in rows:
                key = ("s", m.group(1))
                if key in seen:
                    return
                seen.add(key)
                rec(rows[m.group(1)])
                return
            if n and not n.startswith("$"):
                acc.append(n)
            return
        if _is_elem(n):
            props = n[3]
            if isinstance(props, dict):
                if isinstance(props.get("children"), (str, list)):
                    rec(props["children"])
                tp = props.get("textProps")
                if isinstance(tp, dict) and isinstance(tp.get("children"), (str, list)):
                    rec(tp["children"])
            return
        if isinstance(n, list):
            for x in n:
                rec(x)

    rec(node)
    return acc


def _flight_stream(blob: str) -> List[tuple]:
    """Ordered (kind, text) for the experience card, in display order."""
    rows = _load_flight_rows(blob)
    root = rows.get("0")
    if root is None:
        cand = [v for v in rows.values() if isinstance(v, (list, dict))]
        root = max(cand, key=lambda v: len(json.dumps(v)), default=None)

    out: List[tuple] = []
    seen: set = set()

    def walk(node):
        if isinstance(node, str):
            m = _REF.match(node)
            if m and m.group(1) in rows:
                key = ("w", m.group(1))
                if key in seen:
                    return
                seen.add(key)
                walk(rows[m.group(1)])
            return
        if _is_elem(node):
            tag, props = node[1], node[3]
            if not isinstance(props, dict):
                return
            tp = props.get("textProps")
            if isinstance(tp, dict) and "children" in tp:
                tch = tp["children"]
                expandable = any(
                    k in tp for k in ("expandButtonText", "lineClamp", "hasShowMore")
                )
                if not expandable:
                    bk = props.get("bindingKey")
                    if isinstance(bk, dict) and "expandable_text_block" in json.dumps(bk):
                        expandable = True
                nested = isinstance(tch, list) and tch and isinstance(tch[0], list)
                txt = " ".join(_elem_strings(node, rows, set())).strip()
                if txt:
                    out.append((_DESC if (expandable or nested) else _DETAIL, txt))
                return
            if tag in ("p", "h1", "h2", "h3", "span"):
                txt = " ".join(_elem_strings(node, rows, set())).strip()
                if txt:
                    out.append((_HEADER, txt))
                return
            for k in ("initialItems", "item", "children"):
                if k in props:
                    walk(props[k])
            for k, v in props.items():
                if k not in ("initialItems", "item", "children", "textProps"):
                    walk(v)
            return
        if isinstance(node, list):
            for x in node:
                walk(x)
            return
        if isinstance(node, dict):
            for k in ("initialItems", "item", "children"):
                if k in node:
                    walk(node[k])
            for k, v in node.items():
                if k not in ("initialItems", "item", "children"):
                    walk(v)

    walk(root)
    cleaned: List[tuple] = []
    for kind, t in out:
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            cleaned.append((kind, t))
    return cleaned


# "<EmploymentType> · <tenure>" — a company-group header line (roles follow)
_GROUP_TENURE = _re.compile(
    r"^(Full-time|Part-time|Self-employed|Freelance|Contract|Internship|"
    r"Apprenticeship|Seasonal|Permanent|Temporary)\s*·\s*\d+\s*"
    r"(yr|yrs|year|years|mo|mos|month|months)(\s+\d+\s*(mo|mos|month|months))?$",
    _re.I,
)
# media attachments / app-store links that render in the same slot as a blurb
_MEDIA_JUNK = _re.compile(
    r"://|\.(pdf|png|jpe?g|gif|docx?|pptx?|xlsx?|csv|zip|mp4|mov)$|"
    r"^(Playstore|Play Store|App Store|Download on|View on) ",
    _re.I,
)
_LINKCARD = _re.compile(r"^.{1,45} \| .{1,70}$")     # "Home | OnlyDrops" preview title
_PLACEISH = _re.compile(r"^[A-Z][\w.&'-]*(?:[ ,]+[A-Za-z][\w.&'-]*){0,3}$")


def _looks_like_place(s: str) -> bool:
    return len(s) <= 40 and bool(_PLACEISH.match(s)) and not _is_duration(s)


def _is_group_tenure(s: str) -> bool:
    return _is_bare_tenure(s) or bool(_GROUP_TENURE.match(s))


def _exp_junk(s: str) -> bool:
    return _is_junk(s) or bool(_MEDIA_JUNK.search(s)) or bool(_LINKCARD.match(s))


def _clean_desc(s: str) -> str:
    s = _re.sub(r"\s+", " ", s).strip()
    s = _re.sub(r"\s*…\s*(see|show)\s+more\s*$", "", s, flags=_re.I).strip()
    return s[:3000]


def parse_experience(card_flight: str) -> List[dict]:
    """
    Walk the card's component tree in display order. A `duration` line (year +
    '–'/'to'/'Present') closes an entry, taking the buffered HEADER text as
    (title, company); a company GROUP header (`<Company>` then a bare/typed
    tenure) makes the roles under it inherit that company; a DETAIL line right
    after a duration is the entry's location; a DESC block is its description.
    Undated entries are dropped. On any structural surprise, returns `[]`.
    """
    try:
        stream = _flight_stream(card_flight)
    except Exception:  # noqa: BLE001 - malformed / changed payload => no experience
        return []

    start = next((i for i, (_k, t) in enumerate(stream) if t == "Experience"), None)
    items = stream[start + 1:] if start is not None else stream

    out: List[dict] = []
    buf: List[str] = []                 # pending HEADER text (title / company)
    buf_company: Optional[str] = None   # from a "<Company> · <type>" HEADER
    group_company: Optional[str] = None
    pending_loc: Optional[dict] = None  # entry still eligible for a location line
    expect_group_loc = False
    i, n = 0, len(items)

    while i < n:
        kind, text = items[i]

        if kind == _DESC:
            if out and not out[-1]["description"] and not _exp_junk(text):
                out[-1]["description"] = _clean_desc(text)
            i += 1
            continue

        if text in _SECTION_LABELS and text != "Experience":
            break
        if _exp_junk(text):
            i += 1
            continue

        if _is_duration(text):          # closes an entry, whatever element type
            fields = [t for t in buf if not _is_employment_type(t)]
            if buf_company:
                titles = [t for t in fields if not _COMPANY_TYPE.match(t)]
                company, title = buf_company, (titles[-1] if titles else None)
            elif group_company:
                company, title = group_company, (fields[-1] if fields else None)
            elif len(fields) >= 2:
                title, company = fields[-2], _strip_suffix(fields[-1])
            else:
                title, company = (fields[-1] if fields else None), None
            entry = {"title": title, "company": company, "duration": text,
                     "location": None, "description": None}
            out.append(entry)
            buf, buf_company = [], None
            pending_loc = entry
            expect_group_loc = False
            i += 1
            continue

        if expect_group_loc and _is_locationish(text):
            expect_group_loc = False     # swallow the group's own location line
            i += 1
            continue

        if pending_loc is not None:
            consumed = False
            if pending_loc["location"] is None and (
                _is_locationish(text) or (kind == _DETAIL and _looks_like_place(text))
            ):
                pending_loc["location"] = _strip_suffix(text)
                consumed = True
            pending_loc = None           # only the item directly after a duration
            if consumed:
                i += 1
                continue

        if kind == _DETAIL:
            i += 1                        # stray unmatched date / location — drop
            continue

        # kind == HEADER
        if _is_group_tenure(text):
            if buf:
                group_company = _strip_suffix(buf[-1])
                buf = []
            buf_company = None
            expect_group_loc = True
            pending_loc = None
            i += 1
            continue

        m = _COMPANY_TYPE.match(text)
        if m and not _is_duration(text):
            buf_company = m.group(1).strip()   # standalone entry — ends any group
            group_company = None
            buf.append(text)
            i += 1
            continue

        buf.append(text)
        i += 1

    return out[:40]


_CERTISH = _re.compile(r"\b(Certified|Certificate|Credential|License|Bootcamp)\b", _re.I)


def parse_education(card_flight: str) -> List[dict]:
    """
    The Education card often runs straight into Licenses & certifications /
    Projects with no header leaf between them. We only keep an entry that
    actually looks like schooling: it has a date range, OR a school-name
    keyword (University/Institute/School/…), OR a degree keyword
    (Bachelor/BTech/Diploma/…). Everything else (certs, GitHub project rows)
    is dropped.
    """
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
        looks_like_school = (
            duration is not None
            or _SCHOOL_KW.search(school or "")
            or (degree and _DEGREE_KW.search(degree))
        )
        if school and looks_like_school and not _CERTISH.search(school):
            out.append({"school": school, "degree": degree, "duration": duration})
    return out[:25]


_ENDORSE_COUNT = _re.compile(r"^(\d[\d,]*)\s+endorsements?$", _re.I)
_ENDORSE_JUNK = _re.compile(r"^(Endorsed by\b|·|\d+ (people|person) )", _re.I)


def parse_skills(card_flight: str) -> List[dict]:
    """
    The skills card is a flat list: <skill>, ['Endorsed by …'], ['N endorsements'],
    repeated — no section header. Returns [{name, endorsement_count}].
    Guard: only trust the payload if it actually mentions endorsements.
    """
    lv = text_leaves(card_flight)
    if not lv:
        return []
    # This card slot varies per profile. Only trust it as the skills card if
    # it actually carries endorsement lines — otherwise it's holding "top
    # skills" chrome / positions / project names and we return nothing.
    if not any("endorsement" in x.lower() for x in lv):
        return []
    misfit = {"Experience", "Education", "Interests", "About", "Featured",
              "Licenses & certifications", "Volunteering", "Organizations"}
    if lv[0] in misfit:
        return []
    out: List[dict] = []
    for leaf in lv:
        if leaf in _SECTION_LABELS or _is_junk(leaf) or _ENDORSE_JUNK.match(leaf):
            continue
        if " at " in leaf or len(leaf) > 60:  # position / description, not a skill
            continue
        m = _ENDORSE_COUNT.match(leaf)
        if m:
            if out and out[-1]["endorsement_count"] is None:
                out[-1]["endorsement_count"] = int(m.group(1).replace(",", ""))
            continue
        if 1 <= len(leaf) <= 80:
            out.append({"name": leaf, "endorsement_count": None})
    return out[:60]


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
