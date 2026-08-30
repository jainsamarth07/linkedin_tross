# Project context for Claude Code

## What this is
Tross hiring-challenge submission: "reverse engineer LinkedIn APIs and build a
hosted API that accepts a LinkedIn profile URL and returns most of the profile
page as structured JSON." Public HTTPS deploy, public GitHub repo, README with
setup / API docs / approach / limitations, no secrets in the repo.

**Hard requirement (clarified by the hiring team):** purely reverse-engineered,
hits LinkedIn endpoints directly, **no browser**. No Playwright/Selenium/
headless anything — and no such dependency may be added, not even as a
fallback. The only browser touch is a human copying a session cookie once.

## Approach (shipped)
LinkedIn's profile page is now **Server-Driven UI** ("COMO" / React Server
Components). The API reverse-engineers that — the requests a real browser
actually makes — so traffic blends in and the session survives:

1. `GET /in/<slug>/` → server-rendered **top card** (name, headline, location,
   current_company, followers, connection_degree, website, photos, fsd_profile
   id) parsed from `<title>` + the `window.__como_rehydration__` React-Flight
   blob in `<script id="rehydrate-data">`.
2. `POST /flagship-web/rsc-action/actions/component?componentId=…` ×4 →
   About / Experience / Education / Skills, as React-Flight payloads. Body =
   captured `clientArguments` (~3 KB) templated with slug + profile id.

Auth: `LI_COOKIE_STRING` (full ~15-cookie header incl. PerimeterX `_px3`,
preferred) or `LI_AT_COOKIE` + `LI_JSESSIONID_COOKIE`. All HTTP via `curl_cffi`
with Chrome TLS/HTTP2 impersonation. `OUTBOUND_PROXY` (residential) required on
a datacenter host — LinkedIn kills datacenter-IP sessions fast.

### Dead ends (found, not shipped — kept only as README narrative)
- `/voyager/api/identity/profiles/{id}/profileView` → HTTP 410.
- `/voyager/api/identity/dash/profiles?…&decorationId=FullProfileWithEntities-*`
  → returns data but the web app doesn't call it, so the session is killed
  after ~1 request (302 loop + `Set-Cookie: li_at=delete me`), any IP/account.

## Files (app/)
- `main.py` — FastAPI: `GET /api/profile?url=`, `GET /health`; exception →
  400/401/404/422/429/500.
- `scraper.py` — `scrape_profile(url)`: page → `parse_top_card` → 4 cards
  (best-effort; a blocked card → warning, not failure). `FETCH_DETAIL_CARDS=0`
  skips the cards. Detects self-view and warns.
- `web_client.py` — `WebClient.fetch_profile_html` / `fetch_component`.
- `page_parser.py` — `parse_top_card(html, slug)`, `extract_profile_id`.
  Landmark-anchored only (never hashed CSS classes). Handles JS-escaped /
  entity-escaped image URLs and the `-shrink_`/`-scale_`/`-crop_` transforms.
- `flight_parser.py` — `text_leaves()` + `parse_about/experience/education/
  skills`, `split_date_range`, `is_self_view`. Experience handles single,
  company-grouped, and grouped-then-standalone roles. Education keeps an entry
  only with a date / school-keyword / degree-keyword (drops leaked certs +
  project rows). Skills needs endorsement lines present or returns [].
- `linkedin_http.py` — shared config, `load_cookies()`, `proxies()`,
  `session_was_killed()`, `extract_public_identifier()`, the 3 typed errors
  (`SessionExpiredError`, `ProfileNotFoundError`, `RateLimitedError`).
- `models.py` — response schema. `certifications` / `languages` always `[]`
  (fields kept; parsing out of scope — extra requests / flag risk).

## Verified
Live end-to-end via the FastAPI route from a residential IP (no proxy):
williamhgates, satyanadella, sundarpichai, jeffweiner08, cheshta-satija,
bhavik-malhotra — session held across all. Top card clean everywhere;
experience/education/skills correct on grouped + standalone layouts, degrade
to empty/partial (not wrong) on unusual ones. Deployed on Render
(linkedin-tross.onrender.com). 32 tests, offline (parsers vs
`tests/captures/*`; api tests monkeypatch the scraper).

## Constraints to preserve
- NO BROWSER. Direct HTTP only. The documented further-fallback (if the SDUI
  cards die) is parsing the same Flight payloads from a different endpoint —
  still no browser.
- No third-party scraping API.
- Parsers stay defensive: schema drift degrades a field to null / a section to
  empty + a warning, never a crash.
- `.env` never committed; `.env.example` documents vars with no values.
