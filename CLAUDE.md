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

## Endpoint reality check (done 2026-08-27, live-verified)
The original plan targeted
`/voyager/api/identity/profiles/{publicId}/profileView`. **That endpoint is
dead — HTTP 410.** LinkedIn rebuilt the web profile page on Server-Driven
UI (React Server Components); the browser now POSTs to
`/flagship-web/rsc-action/actions/component?...` and gets React Flight
payloads, not JSON.

Structured data is still available via the newer **`dash` endpoint** (still
used by LinkedIn's mobile clients), which is what this project now calls:
```
GET /voyager/api/identity/dash/profiles
    ?q=memberIdentity&memberIdentity=<slug|profile-id>
    &decorationId=com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93
```
`decorationId` selects a server-side projection; `-93` is the working
version as of Aug 2026 (LinkedIn bumps it). Discovered via
`scripts/probe_endpoints.py`. Verified with live `200` responses; parser
output confirmed correct against the real Bill Gates profile response.

## Architecture (built + live-verified, in app/)
- `models.py` — Pydantic response schema (unchanged).
- `auth.py` — loads `LI_AT_COOKIE` / `LI_JSESSIONID_COOKIE` from env.
  `JSESSIONID` is effectively required now (dash endpoint 302s/403s without
  a matching csrf-token).
- `voyager_client.py` — httpx client. `get_profile()` calls the `dash`
  endpoint above with `PROFILE_DECORATION_ID` (module constant — update
  when the version drifts). Distinct exceptions for: session-kill redirect
  (302 + `Set-Cookie: li_at=delete`), authwall redirect, 401/403, 404,
  429/999.
- `parser.py` — `parse_profile()` (alias `parse_profile_view` kept). The
  dash response is a REST.li `included` list of typed entities under
  `com.linkedin.voyager.dash.` (`identity.profile.Profile`, `.Position`,
  `.Education`, `organization.Company`, `organization.School`,
  `common.Geo`). Star-prefixed fields (`*company`, `*school`, `*geo`) are
  URN refs into the same list — `_Resolver` maps `entityUrn`→entity and
  resolves them. Dates are `dateRange.{start,end}` (`Date` objects), not
  `timePeriod`. Location comes from a `Geo` entity lookup. Still fully
  defensive `.get()` chains.
- `scraper.py` — orchestrates client + parser (`scrape_profile(url)`,
  calls `get_profile` + `parse_profile`).
- `main.py` — unchanged. `GET /api/profile?url=...`, exceptions →
  400/401/404/429/500, `GET /health`.

## Verified
- Live `200` from the dash endpoint with `LI_AT` + `LI_JSESSIONID` set.
- `parse_profile()` run against the real captured response
  (`dash_profile_raw.json`, gitignored): name, headline, location (via Geo
  resolution), about, both images, 3 experiences w/ company logos + date
  ranges, 2 educations w/ school logos + date ranges — all correct.
- 16 tests pass (`tests/fixtures.py` is a synthetic dash-shaped response).
- FastAPI app wires up (`/health`, `/api/profile`, `/docs`).

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
