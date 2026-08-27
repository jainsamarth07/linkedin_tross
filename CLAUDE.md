# Project context for Claude Code

## What this is
A hiring-challenge submission (Tross, deadline 31 Aug) for the brief:
"Reverse engineer LinkedIn APIs and build a hosted API that accepts a
LinkedIn profile URL and returns most of the info on the profile page as
structured JSON." Requirements: public HTTPS deployment, GitHub repo,
README with setup/API docs/approach/limitations, no credentials in the repo.

## Approach chosen (and why)
Considered 3 options before starting:
1. **Voyager internal API** (chosen) — LinkedIn's own web frontend calls
   undocumented REST endpoints under `/voyager/api/...`. Authenticated via
   session cookie, returns clean structured JSON directly — matches the
   brief's literal "reverse engineer the API" framing best.
2. Authenticated headless browser + DOM scraping (Playwright) — considered
   as a fallback/hedge, decided against building both; more brittle to
   LinkedIn's HTML/class-name changes, heavier, slower.
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

## Architecture (already built, in app/)
- `models.py` — Pydantic response schema (LinkedInProfile, Experience,
  Education, Skill, Certification, Language, ProfileImages, ErrorResponse).
- `auth.py` — loads `LI_AT_COOKIE` / `LI_JSESSIONID_COOKIE` from env into
  cookie dicts. Raises clearly if `LI_AT_COOKIE` is missing.
- `voyager_client.py` — httpx-based client. Builds required headers
  (User-Agent, x-restli-protocol-version, csrf-token from JSESSIONID).
  `extract_public_identifier()` parses the `/in/<slug>` out of a profile
  URL. `get_profile_view()` calls
  `/voyager/api/identity/profiles/{publicIdentifier}/profileView`.
  Detects session expiry (redirect to authwall, 401/403), 404, and
  rate-limiting (429/999) as distinct exception types.
- `parser.py` — Voyager returns a flat REST.li `included` list of typed
  entities (`$type` ending in `.Profile`, `.Position`, `.Education`,
  `.Skill`, `.Certification`, `.Language`) rather than one nested document.
  This walks that list and reassembles it into the clean schema. Every
  field access is defensive (`.get()` chains, never raises on a missing
  field) — a schema drift should degrade a field to `null`, not crash the
  request. Unit-tested against a synthetic mock response (see below) —
  **not yet tested against a real live Voyager response**.
- `scraper.py` — orchestrates client + parser into `scrape_profile(url)`.
- `main.py` — FastAPI app. `GET /api/profile?url=...` returns
  `LinkedInProfile` JSON; maps exceptions to 400/401/404/429/500.
  `GET /health` for deploy platform health checks.

## Verified so far
- All modules import cleanly, FastAPI app wires up (`/health`,
  `/api/profile`, `/docs` routes confirmed).
- `parser.py` tested against a hand-built mock Voyager response covering
  Profile/Position/Education/Skill/Certification/Language entities — output
  matches expected schema shape correctly (see git history / chat log for
  the test script if needed).

## NOT yet done — pick up here
1. **Dockerfile** — not yet written.
2. **README.md** — not yet written. Needs: setup instructions (getting the
   li_at/JSESSIONID cookies, env setup), API documentation (endpoint,
   params, example request/response), "approach" section (summarize the
   reasoning above — Voyager over DOM scraping, cookie-reuse over automated
   login), and an honest "known limitations" section — see below.
3. **Live verification against a real LinkedIn account** — the Voyager
   endpoint path, header requirements, and `included` entity field names
   (`firstName`, `geoLocationName`, `timePeriod.startDate.month/year`, etc.)
   were built from general knowledge of this well-documented but
   undocumented-by-LinkedIn API shape. They have NOT been confirmed against
   a live response. First priority when real credentials are available:
   plug in a real `LI_AT_COOKIE`, hit `/api/profile?url=...` against a real
   profile, and diff the actual response's `$type` values and field names
   against what `parser.py` expects. Fix any drift.
4. **Deployment** — not yet decided/configured. Platform TBD (Render /
   Railway / Fly.io / other) — needs a decision, then a Dockerfile +
   platform-specific config (e.g. `render.yaml` or `fly.toml`), then an
   actual deploy + public HTTPS URL for submission.
5. **Known limitations to document honestly in the README** (don't hide
   these — a reviewer will respect an honest limitations section more than
   a submission that pretends these don't exist):
   - Session cookie will eventually expire or get invalidated (password
     change, suspicious-activity flag, manual logout elsewhere) — there is
     no auto-relogin; `SessionExpiredError` surfaces as a 401 with a clear
     message to refresh `LI_AT_COOKIE`.
   - LinkedIn can change Voyager's endpoint paths or entity field names at
     any time without notice; this is unofficial/undocumented API usage.
   - Rate limiting / soft-blocking (999 status) is handled by surfacing a
     429 to the caller, not by automatic backoff/retry — could be added.
   - Profile image extraction (`_best_image_url` in parser.py) assumes a
     `vectorImage`/`artifacts` shape that's the most complex/least certain
     part of the schema — flagged as the most likely thing to need fixing
     against a real response.
   - Only public-profile-page data is covered; nothing behind additional
     access walls (e.g. certain fields LinkedIn restricts based on network
     distance/degree) has been accounted for.

## Constraints / decisions to preserve
- Do not switch to automating the LinkedIn login form — deliberate decision
  to avoid bot-detection risk to the account.
- Do not add a third-party scraping API as a dependency/fallback — would
  undercut the "reverse engineer" requirement of the brief.
- Keep parser.py defensive/non-crashing on missing fields — this is a
  deliberate design choice given the endpoint is undocumented and will
  drift.
- `.env` must never be committed (already in `.gitignore`); `.env.example`
  documents the two required variables without real values.
