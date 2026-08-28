# LinkedIn Profile API

A hosted HTTPS API that accepts a **public LinkedIn profile URL** and returns
most of the information on the profile page as structured JSON.

It works by calling LinkedIn's own internal **Voyager** API — the undocumented
REST endpoints under `/voyager/api/...` that LinkedIn's web and mobile clients
use — authenticated with a session cookie copied from a real browser login.

```
GET /api/profile?url=https://www.linkedin.com/in/<slug>/
```

## Live demo

Deployed on Render: **<https://linkedin-tross.onrender.com>**

```bash
curl -s "https://linkedin-tross.onrender.com/api/profile?url=https://www.linkedin.com/in/williamhgates/" | jq
```

- Interactive docs: <https://linkedin-tross.onrender.com/docs>
- Health: <https://linkedin-tross.onrender.com/health>
- First request after ~15 min idle takes ~50 s (free-tier cold start); subsequent ones are fast.
- If `/api/profile` returns `401`, the LinkedIn session cookie needs a manual refresh — see [limitations](#known-limitations).

---

## Contents
- [Quick start (local)](#quick-start-local)
- [Getting your LinkedIn session cookies](#getting-your-linkedin-session-cookies)
- [API documentation](#api-documentation)
- [Deployment](#deployment)
- [Approach & design decisions](#approach--design-decisions)
- [Known limitations](#known-limitations)
- [Project layout](#project-layout)
- [Development](#development)

---

## Quick start (local)

Requirements: Python 3.11+ (3.12 recommended).

```bash
git clone <this-repo>
cd linkedin-profile-api

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and paste in LI_AT_COOKIE + LI_JSESSIONID_COOKIE (see next section)

uvicorn app.main:app --reload
```

Then:

```bash
curl "http://localhost:8000/api/profile?url=https://www.linkedin.com/in/williamhgates/"
```

Interactive docs (Swagger UI): <http://localhost:8000/docs>

### Run with Docker

```bash
docker build -t linkedin-profile-api .
docker run -p 8000:8000 --env-file .env linkedin-profile-api
```

---

## Getting your LinkedIn session cookies

This API does **not** log in for you. You log in once in a normal browser and
copy the resulting session cookies into environment variables. (Rationale in
[Approach](#approach--design-decisions).)

1. **Use a real, aged account** (yours or a long-lived secondary). Brand-new
   throwaway accounts get challenged fast regardless of anything else — see
   [limitations](#known-limitations).
2. Log into <https://www.linkedin.com> in Chrome or Firefox as normal.
3. Open DevTools → **Network** tab. Reload the page. Right-click any
   `www.linkedin.com` request → **Copy → Copy as cURL**.
4. From that cURL, take the **`-b '…'`** (or `-H 'cookie: …'`) value — one long
   line, ~15 `name=value;` pairs (`li_at`, `JSESSIONID`, `bcookie`, `lidc`,
   `_px3`, …) — and set it as **`LI_COOKIE_STRING`** in `.env`. That's the
   whole browser session; the app parses `JSESSIONID` out of it for CSRF.
5. **Do not click "Log out"** afterwards — that server-invalidates the session.
   Just close the tab.

> Minimal alternative: set only `LI_AT_COOKIE` + `LI_JSESSIONID_COOKIE` (both
> from the same login; `li_at` is `HttpOnly` so read it from the *Application →
> Cookies* panel). Thinner and more bot-like — prefer `LI_COOKIE_STRING`.

### Environment variables

| Variable                | Required | Purpose |
|-------------------------|----------|---------|
| `LI_COOKIE_STRING`      | **Yes** (recommended form) | The **full** `cookie:` header from a real logged-in browser request (DevTools → Network → any `linkedin.com` request → Copy → Copy as cURL → the `-b '…'` / `-H 'cookie: …'` value, one line). ~15 cookies incl. the PerimeterX `_px3`. `JSESSIONID` is parsed out of it for the `csrf-token` header. |
| `LI_AT_COOKIE`          | Fallback | Used only if `LI_COOKIE_STRING` is unset. Just `li_at` — thinner, more bot-like. |
| `LI_JSESSIONID_COOKIE`  | Fallback | Paired with `LI_AT_COOKIE`; supplies `csrf-token`. |
| `OUTBOUND_PROXY`        | **Yes** on a datacenter host | Full proxy URL (`http://user:pass@host:port`). LinkedIn scores datacenter IPs (Render/Fly/…) as high-risk — route through a residential/mobile proxy. Leave unset for local runs from a home IP. |
| `FETCH_DETAIL_CARDS`    | No | `0` to skip the About/Experience/Education `rsc-action` calls and serve the top card only (fewer requests). Default on. |
| `IMPERSONATE_TARGET`    | No | `curl_cffi` browser profile for the TLS/HTTP2 fingerprint. Default `chrome136`. |
| `LI_CLIENT_VERSION`     | No | `x-li-track` clientVersion; auto-read from the page HTML, this is the fallback. |
| `PORT`                  | No | Port to bind (injected by most PaaS hosts; defaults to `8000`). |

`.env` is git-ignored. `.env.example` documents the variables with no values.
Never commit real cookies.

---

## API documentation

### `GET /health`

Liveness check for deploy platforms.

```json
{ "status": "ok" }
```

### `GET /api/profile`

| Query param | Type   | Required | Description |
|-------------|--------|----------|-------------|
| `url`       | string | yes      | Full profile URL, e.g. `https://www.linkedin.com/in/williamhgates/`. Query string and trailing slash are fine; the `/in/<slug>` segment is what matters. |

#### Success — `200 OK`

Returns a `LinkedInProfile`. Every field is best-effort: anything the parser
could not confidently extract comes back as `null` (or an empty list), and
`warnings` explains what was missing rather than failing the request.

The block below is **real output** (Bill Gates' public profile, image URLs
trimmed), Aug 2026:

```jsonc
{
  "profile_url": "https://www.linkedin.com/in/williamhgates/",
  "name": "Bill Gates",
  "headline": "Chair, Gates Foundation and Founder, Breakthrough Energy",
  "location": "Seattle, Washington, United States",
  "current_company": "Gates Foundation",
  "about": "Chair of the Gates Foundation. Founder of Breakthrough Energy. Co-founder of Microsoft. Voracious reader. Avid traveler. Active blogger.",
  "connections": null,           // shown only for some viewer/degree combos
  "connection_degree": "3rd",
  "followers": "40,601,261",
  "website": null,               // behind a click on the real page
  "images": {
    "profile_photo_url": "https://media.licdn.com/dms/image/v2/.../profile-displayphoto-shrink_800_800/...",
    "background_photo_url": "https://media.licdn.com/dms/image/v2/.../profile-displaybackgroundimage-shrink_350_1400/..."
  },
  "experience": [
    { "title": "Co-chair",   "company": "Gates Foundation",     "duration": "2000 – Present", "start_date": "2000", "end_date": null, "location": null },
    { "title": "Founder",     "company": "Breakthrough Energy",  "duration": "2015 – Present", "start_date": "2015", "end_date": null, "location": null },
    { "title": "Co-founder",  "company": "Microsoft",            "duration": "1975 – Present", "start_date": "1975", "end_date": null, "location": null }
  ],
  "education": [
    { "school": "Harvard University", "degree": null, "duration": "1973 – 1975", "start_date": "1973", "end_date": "1975" },
    { "school": "Lakeside School",    "degree": null, "duration": null,          "start_date": null,   "end_date": null }
  ],
  "skills": [],                   // separate rsc-action card, not fetched
  "certifications": [],
  "languages": [],
  "scraped_at": "2026-08-29T00:00:00+00:00",
  "warnings": []
}
```

`name` / `headline` / `location` / `current_company` / `followers` / `images`
come from the page HTML and are reliable. `about` / `experience` / `education`
come from the detail cards — best-effort; on a blocked card they're empty and a
`warnings` line says so.

#### Errors

All errors share the shape `{ "error": "<message>", "detail": null }`.

| Status | When | What to do |
|--------|------|------------|
| `400`  | The `url` isn't a parseable LinkedIn profile URL. | Fix the URL. |
| `401`  | Session cookie expired / flagged, or LinkedIn returned a cookie-delete redirect / authwall. | Refresh `LI_COOKIE_STRING` from a browser. |
| `404`  | LinkedIn returned no profile for that slug. | Check the slug exists / is public. |
| `422`  | The `url` query param is missing entirely. | Provide `?url=...`. |
| `429`  | LinkedIn rate-limited or soft-blocked (`429` / `999`). | Back off and retry later. No automatic retry. |
| `500`  | Anything unexpected. | Check server logs. |

#### Example

```bash
curl -s "https://<your-deployment>/api/profile?url=https://www.linkedin.com/in/williamhgates/" | jq
```

---

## Deployment

The repo ships a platform-agnostic **`Dockerfile`** plus a **`render.yaml`**
blueprint for [Render](https://render.com).

### Render (default, what `render.yaml` configures)

1. Push this repo to GitHub.
2. Render dashboard → **New +** → **Blueprint** → pick the repo. It reads
   `render.yaml` and creates a Docker web service with a `/health` check.
3. In the service's **Environment** settings add `LI_AT_COOKIE`,
   `LI_JSESSIONID_COOKIE`, and `OUTBOUND_PROXY` (all declared `sync: false`, so
   Render prompts for them and never stores them in the repo).
   **`OUTBOUND_PROXY` is not optional here** — without a residential proxy,
   Render's datacenter IP gets the LinkedIn session killed after ~1 request.
4. Deploy → public `https://<name>.onrender.com` URL.

**Cold starts:** Render's free web service spins down after ~15 min idle and
takes ~50 s to wake. For a low-traffic demo that's fine; if it matters, point a
free uptime pinger (cron-job.org, UptimeRobot) at `/health` every 10 min, or
use a host without scale-to-zero.

### Any other Docker host (Fly.io, Railway, a VM, …)

The `Dockerfile` is all you need — it honours `$PORT` and binds `0.0.0.0`. Set
the same env vars. For Fly.io, `fly launch` detects the Dockerfile; set
`min_machines_running = 1` in `fly.toml` to avoid scale-to-zero.

---

## Approach & design decisions

### Why the Voyager internal API

The brief requires a **purely reverse-engineered solution that hits LinkedIn
endpoints directly and does not use a browser**. That rules out anything
DOM/render-based and points straight at LinkedIn's internal HTTP API.

| Option | Verdict |
|--------|---------|
| **LinkedIn's internal Voyager API** (`/voyager/api/...`), called directly over HTTP | **Chosen.** Direct HTTP to LinkedIn's own endpoints, no browser. Authenticated with a session cookie, returns structured REST.li JSON — no HTML parsing. |
| Headless browser + DOM scraping (Playwright/Selenium) | **Excluded by the brief** (no browser). Also heavier, slower, and brittle to markup changes. No browser-automation dependency exists in this repo. |
| Third-party scraper APIs (Proxycurl, PhantomBuster, …) | Rejected: doesn't satisfy "build a hosted API" / "reverse engineer". |
| Official LinkedIn OAuth API | Rejected: only exposes the *authenticated user's own* data, not arbitrary third-party profiles. |

The only browser involvement anywhere is a **one-time manual login** to copy
the session cookie (below) — a human logging in once, not automation.

### TLS / HTTP2 fingerprint

A plain Python HTTP client (`httpx`, `requests`) has a TLS **JA3/JA4** and
HTTP/2 **SETTINGS** fingerprint that matches no real browser — an independent
bot signal on top of headers and IP. The Voyager calls therefore go through
[`curl_cffi`](https://github.com/lexiforest/curl_cffi) with
`impersonate="chrome136"` (override via `IMPERSONATE_TARGET`), so the
handshake matches Chrome. `httpx` is still used elsewhere (the test client).
This does **not** substitute for a good IP — pair it with `OUTBOUND_PROXY`.

### Why a copied cookie instead of automated login

Driving LinkedIn's username/password form with a headless browser reliably trips
LinkedIn's bot defenses (CAPTCHA / email or phone "checkpoints") because from an
unrecognised device it looks like credential stuffing — and can lock the
account. Instead: log in **once, manually, in a real browser**, copy `li_at` +
`JSESSIONID` into env vars, and replay them on every API call
([`app/auth.py`](app/auth.py)). The trade-off is a manually-managed secret with
a finite, and in practice short, lifetime — see limitations.

### What this project actually calls

LinkedIn's web app has moved on twice:

1. `/voyager/api/identity/profiles/{id}/profileView` — the endpoint every
   open-source wrapper uses — now returns **HTTP 410 Gone**.
2. `/voyager/api/identity/dash/profiles?...&decorationId=FullProfileWithEntities-*`
   — the newer REST.li endpoint — still returns data, but LinkedIn's bot
   defense (PerimeterX + monitoring of this now-unused endpoint) **kills the
   session after ~1 request**, from any IP, on any account. Not usable for an
   API. (Kept in [`app/voyager_client.py`](app/voyager_client.py) +
   [`app/parser.py`](app/parser.py) as a documented dead end; probe that found
   it: [`scripts/probe_endpoints.py`](scripts/probe_endpoints.py).)

The current web profile page is **Server-Driven UI** (LinkedIn's "COMO"
framework — React Server Components). This project reverse-engineers *that*,
because those requests are the ones a real browser actually makes, so they
don't get the instant kill:

| Step | Request | Yields |
|---|---|---|
| 1 | `GET /in/<slug>/` | The server-rendered **top card** — name, headline, location, current company, followers, connection degree, website, profile + background photo, and the `fsd_profile` id. Parsed from the `<title>` and the `window.__como_rehydration__` React-Flight blob in `<script id="rehydrate-data">` ([`app/page_parser.py`](app/page_parser.py)). |
| 2a | `POST /flagship-web/rsc-action/actions/component?componentId=…profileCardsAboveActivity` | **About** |
| 2b | `…profileCardsExperienceOnly` | **Experience** |
| 2c | `…profileCardsBelowActivityPart1WithoutExp` | **Education** |

Step 2 posts the ~3 KB `clientArguments` body LinkedIn's client sends
(templated with the slug + profile id) and gets back a React-Flight payload —
newline-separated `<id>:<json>` rows whose `"children":["…text…"]` leaves,
read in order and split on section landmarks, give the section content
([`app/flight_parser.py`](app/flight_parser.py)).

### Request flow

```
URL ─▶ extract_public_identifier()                       (voyager_client.py)
    ─▶ WebClient.fetch_profile_html(slug)  GET /in/<slug>/
    ─▶ parse_top_card(html, slug)                          (page_parser.py)
    ─▶ WebClient.fetch_component() ×3      POST rsc-action/actions/component   [best-effort]
    ─▶ parse_about / parse_experience / parse_education    (flight_parser.py)
    ─▶ LinkedInProfile JSON                                (main.py)
```

Step 1 is the reliable core (always returns). Step 2 is best-effort: if a card
call is blocked, that section comes back empty with a `warnings` entry rather
than failing the request. Set `FETCH_DETAIL_CARDS=0` to skip step 2 entirely
and serve the top card only.

---

## Known limitations

These are real. An honest list beats a submission that pretends they don't exist.

- **LinkedIn's bot defense is aggressive, and sessions get killed fast —
  especially from datacenter IPs.** During development, a burst of ~12
  endpoint-probe requests from a residential IP got the session flagged;
  LinkedIn then responded `302` to a redirect loop with
  `Set-Cookie: li_at=delete me` (a hard session kill). The legacy
  `dash/profiles` endpoint was killed after ~1 request every time — that path
  is a dead end. The **current SDUI approach this project uses** (page +
  `rsc-action` cards — the calls a real browser makes) held up across many
  profiles in testing, from a residential IP, without a kill. The client still
  detects the kill response and raises `SessionExpiredError` → `401`; there is
  **no auto-relogin**. Practical consequences:
  - **From a datacenter IP (Render/Fly/…) set `OUTBOUND_PROXY` to a
    residential/mobile proxy.** LinkedIn scores datacenter ranges as
    high-risk regardless of how clean the request looks. On a residential IP,
    no proxy is needed for light use.
  - Give it a full browser session: set **`LI_COOKIE_STRING`** (the whole
    `cookie:` header, ~15 cookies incl. the PerimeterX `_px3`), not just
    `li_at` + `JSESSIONID`.
  - Keep volume modest and paced (the app makes 1 + 3 requests per profile).
    Community-reported sustainable rates on an aged account are
    ~100–300 profiles/day.
  - Expect to refresh the cookie periodically. No throttle/backoff or
    account-pool is built in — that's what a production version would add.
- **Experience / Education are best-effort.** They're read from the Flight
  card payloads by taking text leaves in order and splitting on the per-entry
  date line. This is exact for ordinary roles and for company-grouped / board
  roles; it can mis-group or drop an entry on unusual layouts (roles with no
  dates, heavy nesting, media attachments). The **top card is not affected** —
  name / headline / location / company / followers / photos come from the
  server-rendered page and are reliable.
- **Skills, certifications, languages** are separate `rsc-action` cards that
  aren't fetched (more requests = more risk). Returned `[]` with a warning.
  Adding them is a matter of one more component call each.
- **`connections`** is only present for some viewer/degree combinations
  (`followers` is shown instead for creators). `connection_degree` likewise.
- **Hashed CSS classes / component ids will churn.** Extraction is anchored on
  stable landmarks (`<title>`, `firstName`/`lastName` JSON, the `"… followers"`
  / `"Contact info"` leaves, `licdn` URLs, the `"About"`/`"Experience"`/
  `"Education"` section labels), never class names. Component ids
  (`profileCardsExperienceOnly`, …) and the `clientArguments` body shape can
  still change — re-capture from a live session if a card returns nothing.
- **Verified on a modest sample** of real profiles (Gates, Nadella, Weiner,
  Pichai, others), Aug 2026. Deactivated / heavily-restricted / RTL-name
  profiles not exhaustively covered.
- **Rate limiting is surfaced, not absorbed.** `429` / `999` → HTTP `429`.
- **Public-profile data only** — what your logged-in session can see.
- **No posts / recommendations / volunteering / projects / publications.**

---

## Project layout

```
app/
  main.py            FastAPI app: routes, exception -> HTTP status mapping
  scraper.py         orchestrates: page -> top card -> 3 detail cards -> merge
  web_client.py      curl_cffi client: GET /in/<slug>/ ; POST rsc-action cards
  page_parser.py     profile-page HTML -> top card (title + __como_rehydration__)
  flight_parser.py   React-Flight payload -> ordered text leaves -> about /
                     experience / education
  models.py          Pydantic response schema
  auth.py            loads cookies (LI_COOKIE_STRING or li_at + JSESSIONID)
  templates/
    rsc_component_body.json.tpl   captured rsc-action body, {VANITY}/{PROFILE_ID}
  voyager_client.py  DEAD-END dash/profiles client (kept + documented); also
                     the shared curl_cffi/cookie/impersonation helpers
  parser.py          dash-schema REST.li parser (paired with voyager_client)
scripts/
  dump_voyager.py    one careful request against the dash endpoint
  probe_endpoints.py the sweep that found the (now dead-end) dash endpoint
tests/
  test_page_parser.py    top-card parse vs. tests/captures/mini_profile.html
  test_flight_parser.py   about/experience/education vs. real *.flight captures
  test_parser.py          dash-schema parser vs. synthetic fixture
  test_api.py             endpoint wiring + exception -> status-code mapping
  captures/               real Flight card payloads + a mini HTML fixture
Dockerfile
render.yaml          Render blueprint      fly.toml   Fly.io (never-sleep) config
.env.example
```

---

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

30 tests, no network required (parsers run against committed captures; the API
tests monkeypatch the scraper).

To re-capture live card payloads after a cookie refresh, load a profile in a
logged-in browser with DevTools → Network open, and copy the
`rsc-action/actions/component` responses / the `/in/<slug>/` document.

`scripts/probe_endpoints.py` fires a spaced-out sweep of candidate endpoints —
useful only when the primary endpoint breaks and you need to find its
replacement. It will get your session flagged; run it sparingly.
