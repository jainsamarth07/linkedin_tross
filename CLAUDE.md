# Project context for Claude Code

## What this is
A hiring-challenge submission (Tross, deadline 31 Aug) for the brief:
"Reverse engineer LinkedIn APIs and build a hosted API that accepts a
LinkedIn profile URL and returns most of the info on the profile page as
structured JSON." Requirements: public HTTPS deployment, GitHub repo,
README with setup/API docs/approach/limitations, no credentials in the repo.

## Approach chosen (and why)
HARD REQUIREMENT (clarified by the hiring team by email): a purely
reverse-engineered solution that hits LinkedIn endpoints directly and
**does not use a browser**. No Playwright/Selenium/headless anything. The
repo has zero browser-automation dependencies and must stay that way.

Options considered:
1. **Voyager internal API** (chosen) — call LinkedIn's undocumented REST
   endpoints under `/voyager/api/...` directly with httpx. Authenticated
   via session cookie, returns structured REST.li JSON. Satisfies the
   direct-HTTP / no-browser requirement.
2. Headless browser + DOM scraping (Playwright/Selenium) — **excluded by
   the brief.** Also heavier/slower/brittle. Not built, not a dependency.
3. Third-party scraper APIs (Proxycurl, PhantomBuster, etc.) — rejected,
   doesn't satisfy "build a hosted API" / "reverse engineer" requirement.
4. Official LinkedIn OAuth API — rejected, only exposes the authenticated
   user's own data, not arbitrary third-party profiles.

**Auth strategy**: explicitly NOT automating the LinkedIn login form with a
headless browser — that pattern reliably triggers LinkedIn's bot defenses
(CAPTCHA / checkpoint) since it looks like credential stuffing. Instead: log
in manually once in a real browser, copy the `li_at` session cookie (and
optionally `JSESSIONID` for the CSRF token) into env vars, and reuse that
session for all API calls. This is documented explicitly in `app/auth.py`
and needs to go in the README's "approach" section too.

## Endpoint history (2026-08-27 → 08-29, all live-verified)
1. `/voyager/api/identity/profiles/{id}/profileView` — **HTTP 410, gone.**
2. `/voyager/api/identity/dash/profiles?...&decorationId=FullProfileWithEntities-93`
   — returns data, but LinkedIn (PerimeterX `_px3` + monitoring of this
   now-unused endpoint) **kills the session after ~1 request**, every time,
   any IP/account. **Dead end.** Kept in `voyager_client.py` + `parser.py`
   as documented; `scripts/probe_endpoints.py` is how it was found.
3. **SDUI / "COMO" (current web app) — what the project uses now.** The
   profile page is React Server Components. We hit the same requests a real
   browser makes, so no instant kill:
   - `GET /in/<slug>/` → server-rendered **top card** in the HTML
     (`<title>` + `window.__como_rehydration__` Flight blob):
     name, headline, location, current_company, followers,
     connection_degree, website, photos, `fsd_profile` id.
   - `POST /flagship-web/rsc-action/actions/component?componentId=…`
     ×3 → about / experience / education, as React-Flight payloads.
     Body = captured `clientArguments` (~3KB) templated with slug + id.
   Verified live across many profiles (Gates, Nadella, Weiner, Pichai, …)
   from a residential IP — session survived.

## Architecture (app/)
- `web_client.py` — curl_cffi client. `fetch_profile_html(slug)` (GET page),
  `fetch_component(component, slug, pid)` (POST rsc-action). Reuses the
  cookie / impersonation / proxy / session-kill-detection helpers from
  `voyager_client.py`.
- `page_parser.py` — `parse_top_card(html, slug)`. Landmark-anchored
  (`<title>`, `firstName`/`lastName` JSON near the slug, `"N followers"` /
  `"Contact info"` leaves, `licdn` URLs) — never hashed CSS classes.
  `extract_profile_id(html)` pulls `vieweeProfileId`.
- `flight_parser.py` — `text_leaves()` pulls ordered `"children":["…"]`
  strings from a Flight payload (JS-escaped rehydration OR raw rsc
  response). `parse_about/experience/education` split those on section
  labels; experience flushes an entry per date line (best-effort on
  dateless / deeply-nested layouts).
- `scraper.py` — `scrape_profile(url)`: page → top card → 3 cards
  (best-effort; card failure → warning, not request failure). Env
  `FETCH_DETAIL_CARDS=0` skips the cards.
- `auth.py` — `LI_COOKIE_STRING` (full ~15-cookie header, preferred) or
  `LI_AT_COOKIE` + `LI_JSESSIONID_COOKIE`. `app/__init__.py` loads `.env`.
- `voyager_client.py` / `parser.py` — the dead-end dash path, kept +
  documented. Also home of the shared curl_cffi helpers.
- `models.py` — added `current_company`, `connection_degree`, `website`.
- `main.py` — unchanged (`GET /api/profile`, `GET /health`).

## Verified
- Live: `GET /in/<slug>/` + 3 rsc-action cards, run through the FastAPI
  route, for williamhgates / satyanadella / sundarpichai / jeffweiner08 /
  agrawal-parag — session held across all of them from a residential IP,
  no proxy. Full profiles returned (top card always clean; experience
  best-effort — ordinary + board/grouped roles parse right, very unusual
  layouts can mis-group).
- 30 tests pass, offline (parsers vs real `tests/captures/*.flight` +
  a mini HTML fixture; api tests monkeypatch the scraper).

## NOT yet done — pick up here
1. **Dockerfile** — DONE (`Dockerfile` + `.dockerignore`, platform-agnostic,
   honours `$PORT`). Not yet built/run locally (no Docker daemon in dev env).
2. **README.md** — DONE. Setup, cookie steps, API docs (with a real verified
   example response), approach (incl. the 410 / SDUI discovery), honest
   limitations.
3. **Live verification** — DONE for the happy path (see Verified above).
   Still untested: profiles with no experience, non-Latin names, deactivated
   / heavily-restricted profiles.
4. **Deployment** — chosen: **Render** (`render.yaml` written — Docker web
   service, `/health` check, `LI_AT_COOKIE`/`LI_JSESSIONID_COOKIE` as
   `sync: false`). Not yet deployed. Need: push to GitHub, create the
   blueprint, set the two secrets, deploy, grab the public HTTPS URL. NOTE:
   test from the deployed box's IP — see limitation below.
5. **Skills / certifications / languages** — the `-93` projection does NOT
   inline them; they return `[]` with a warning. They need separate
   `dash/profileSkills` etc. calls. Deliberately not added: extra requests
   per profile materially raise the flagging risk (see below). Add later
   only if request budget allows.
6. **`connections` / `followers`** — also not in this projection; always
   `null` currently.

## Key operational limitation discovered
LinkedIn's bot defense is **aggressive**. A ~12-request probe burst from a
residential IP got the session flagged; after that, LinkedIn killed even a
freshly-issued cookie within 1–2 requests (`302` redirect loop +
`Set-Cookie: li_at=delete me`). Implications baked into the design:
- **one Voyager call per profile**, no burst/backfill;
- expect frequent cookie refreshes; there is no auto-relogin;
- a flagged IP stays hot for hours — the deploy IP matters;
- `scripts/probe_endpoints.py` will flag a session; run it sparingly.
Documented in README "Known limitations" along with: decorationId version
drift, undocumented-API drift generally, rate-limit surfaced-not-absorbed,
public-data-only, single-endpoint scope.

## Constraints / decisions to preserve
- NO BROWSER. Direct HTTP to LinkedIn endpoints only (hiring-team
  requirement). Never add Playwright/Selenium/puppeteer/headless-Chrome —
  not as the solution, not as a fallback, not as a dev dependency. The
  documented fallback (if the dash endpoint dies) is parsing the SDUI
  `rsc-action` React Flight payloads — still direct HTTP.
- Do not automate the LinkedIn login form — cookie is copied manually once
  by a human (the one allowed browser touch). Avoids bot-detection on login.
- Do not add a third-party scraping API as a dependency/fallback — would
  undercut the "reverse engineer" requirement of the brief.
- Keep parser.py defensive/non-crashing on missing fields — this is a
  deliberate design choice given the endpoint is undocumented and will
  drift.
- `.env` must never be committed (already in `.gitignore`); `.env.example`
  documents the two required variables without real values.
