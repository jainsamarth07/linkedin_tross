# LinkedIn Profile API

A hosted HTTPS API that accepts a **public LinkedIn profile URL** and returns
most of the information on the profile page as structured JSON.

It works by calling LinkedIn's own internal **Voyager** API — the undocumented
REST endpoints under `/voyager/api/...` that LinkedIn's web and mobile clients
use — authenticated with a session cookie copied from a real browser login.

```
GET /api/profile?url=https://www.linkedin.com/in/<slug>/
```

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

1. **Use a secondary / throwaway LinkedIn account.** Automated use gets a
   session flagged quickly — see [limitations](#known-limitations). Don't use
   your primary account.
2. Log into <https://www.linkedin.com> in Chrome or Firefox as normal.
3. Open DevTools (`Cmd+Option+I` / `Ctrl+Shift+I`):
   - **Chrome:** *Application* tab → *Storage* → *Cookies* → `https://www.linkedin.com`
   - **Firefox:** *Storage* tab → *Cookies* → `https://www.linkedin.com`
4. Copy **`li_at`** → `LI_AT_COOKIE` (a ~150–200 char string; does **not**
   start with `ajax:`).
5. Copy **`JSESSIONID`** → `LI_JSESSIONID_COOKIE` (looks like
   `"ajax:1234567890123456789"`, quotes included). Used to build the
   `csrf-token` header the `dash` endpoint requires. **Grab it in the same
   sitting as `li_at`** — the two must belong to the same session or CSRF
   checks fail.
6. **Do not click "Log out"** afterwards — that server-invalidates the cookie.
   Just close the tab.

> `li_at` is `HttpOnly`, so `document.cookie` in the console won't show it —
> the Application/Storage tab is the only way to read it.

### Environment variables

| Variable                | Required | Purpose |
|-------------------------|----------|---------|
| `LI_AT_COOKIE`          | **Yes**  | LinkedIn session cookie. The app refuses to start a request without it. |
| `LI_JSESSIONID_COOKIE`  | **Yes** in practice | Supplies the `csrf-token` header. The `dash` profile endpoint 302s / 403s without a matching CSRF token. |
| `PORT`                  | No       | Port to bind (injected by most PaaS hosts; defaults to `8000`). |

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

The block below is a **real, verified** response (Bill Gates' public profile,
trimmed), so it reflects exactly what the current endpoint returns — including
the fields it does **not** populate:

```jsonc
{
  "profile_url": "https://www.linkedin.com/in/williamhgates/",
  "name": "Bill Gates",
  "headline": "Chair, Gates Foundation and Founder, Breakthrough Energy",
  "location": "Seattle, Washington, United States",
  "about": "Chair of the Gates Foundation. Founder of Breakthrough Energy. Co-founder of Microsoft. Voracious reader. Avid traveler. Active blogger.",
  "connections": null,          // not in this endpoint's projection
  "followers": null,            // not in this endpoint's projection
  "images": {
    "profile_photo_url": "https://media.licdn.com/dms/image/v2/.../profile-displayphoto-shrink_800_800/...",
    "background_photo_url": "https://media.licdn.com/dms/image/v2/.../profile-displaybackgroundimage-shrink_350_1400/..."
  },
  "experience": [
    {
      "title": "Co-chair",
      "company": "Gates Foundation",
      "employment_type": null,
      "duration": "2000 - Present",
      "start_date": "2000",
      "end_date": null,
      "location": null,
      "description": null,
      "company_logo_url": "https://media.licdn.com/dms/image/v2/.../company-logo_400_400/..."
    },
    {
      "title": "Co-founder",
      "company": "Microsoft",
      "duration": "1975 - Present",
      "start_date": "1975",
      "end_date": null,
      "company_logo_url": "https://media.licdn.com/dms/image/v2/.../microsoft_logo..."
    }
  ],
  "education": [
    {
      "school": "Harvard University",
      "degree": null,
      "field_of_study": null,
      "duration": "1973 - 1975",
      "start_date": "1973",
      "end_date": "1975",
      "description": null,
      "school_logo_url": "https://media.licdn.com/dms/image/v2/.../company-logo_400_400/..."
    }
  ],
  "skills": [],                 // see limitations — separate endpoint, not called
  "certifications": [],         // see limitations
  "languages": [],              // see limitations
  "scraped_at": "2026-08-27T12:00:00+00:00",
  "warnings": [
    "Skills, certifications and languages are not included by this endpoint's projection and are returned empty (see README limitations)."
  ]
}
```

#### Errors

All errors share the shape `{ "error": "<message>", "detail": null }`.

| Status | When | What to do |
|--------|------|------------|
| `400`  | The `url` isn't a parseable LinkedIn profile URL. | Fix the URL. |
| `401`  | Session cookie is expired/invalid/flagged, or Voyager returned 401/403 / a cookie-delete redirect. | Get a fresh `li_at` + `JSESSIONID` from a browser (secondary account). |
| `404`  | LinkedIn returned no profile for that slug. | Check the slug exists / is public. |
| `422`  | The `url` query param is missing entirely. | Provide `?url=...`. |
| `429`  | LinkedIn rate-limited or soft-blocked the request (HTTP `429` or LinkedIn's `999`). | Back off and retry later. No automatic retry. |
| `500`  | Anything unexpected (e.g. Voyager returned non-JSON). | Check server logs. |

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
3. In the service's **Environment** settings add `LI_AT_COOKIE` and
   `LI_JSESSIONID_COOKIE` (declared `sync: false`, so Render prompts for them
   and never stores them in the repo).
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

Four options were considered:

| Option | Verdict |
|--------|---------|
| **LinkedIn's internal Voyager API** (`/voyager/api/...`) | **Chosen.** Literally "the LinkedIn API" the brief asks to reverse-engineer. Authenticated with a session cookie, returns structured REST.li JSON — no HTML parsing. |
| Authenticated headless browser + DOM scraping (Playwright) | Considered as a hedge. Heavier, slower, and brittle to markup changes. Kept as a documented fallback (see below) but not built. |
| Third-party scraper APIs (Proxycurl, PhantomBuster, …) | Rejected: doesn't satisfy "build a hosted API" / "reverse engineer". |
| Official LinkedIn OAuth API | Rejected: only exposes the *authenticated user's own* data, not arbitrary third-party profiles. |

### Why a copied cookie instead of automated login

Driving LinkedIn's username/password form with a headless browser reliably trips
LinkedIn's bot defenses (CAPTCHA / email or phone "checkpoints") because from an
unrecognised device it looks like credential stuffing — and can lock the
account. Instead: log in **once, manually, in a real browser**, copy `li_at` +
`JSESSIONID` into env vars, and replay them on every API call
([`app/auth.py`](app/auth.py)). The trade-off is a manually-managed secret with
a finite, and in practice short, lifetime — see limitations.

### The endpoint moved — what this project actually calls

The classic bundled endpoint
`/voyager/api/identity/profiles/{publicId}/profileView` that most open-source
LinkedIn wrappers use **is gone** — it now returns **HTTP 410**. LinkedIn
rebuilt the web profile page on **Server-Driven UI (React Server Components)**:
the browser now POSTs to `/flagship-web/rsc-action/actions/component?...` and
gets back React Flight payloads (serialized component trees), not a clean JSON
document.

The structured data is still reachable through the newer **"dash" (Data Access
Layer) endpoint**, which the mobile clients still use:

```
GET /voyager/api/identity/dash/profiles
    ?q=memberIdentity
    &memberIdentity=<publicIdentifier | profile-id>
    &decorationId=com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93
```

`decorationId` is a server-side projection selector — it controls which nested
entities get inlined into the response. `-93` is the version confirmed working
in Aug 2026; LinkedIn bumps the number periodically. This was found by probing
sibling endpoints once the web app stopped revealing them
([`scripts/probe_endpoints.py`](scripts/probe_endpoints.py)).

### How a Voyager response becomes the schema

The `dash` response follows the REST.li **`included`** convention: a flat list
of typed entities (`$type` under `com.linkedin.voyager.dash.` — `.Profile`,
`.Position`, `.Education`, `organization.Company`, `organization.School`,
`common.Geo`), cross-referenced by `entityUrn`. Star-prefixed fields
(`*company`, `*school`, `*geo`) hold a URN pointing at a sibling entity.
[`app/parser.py`](app/parser.py) builds a URN→entity map, walks the list by
`$type`, resolves the refs, and assembles a `LinkedInProfile`. Every read is a
defensive `.get()` chain: **schema drift degrades one field to `null`, it does
not crash the request**, and `warnings` records what was missing.

### Request flow

```
URL ──▶ extract_public_identifier()      (app/voyager_client.py)
     ──▶ VoyagerClient.get_profile()     → GET /voyager/api/identity/dash/profiles?q=memberIdentity&…&decorationId=…
     ──▶ parse_profile()                 (app/parser.py)  — REST.li `included` list → LinkedInProfile
     ──▶ LinkedInProfile JSON            (app/main.py)
```

### Fallback if the `dash` endpoint is also retired

If `FullProfileWithEntities-*` stops working entirely, the next step is to parse
the SDUI React Flight payloads from the `rsc-action/actions/component` endpoints
(the data — name, headline, about, experience, education — is present in them as
text nodes), or to render the page in a cookie-authenticated headless browser
(no login automation) and scrape the DOM. Both are heavier and more brittle than
the current approach, which is why they're the fallback.

---

## Known limitations

These are real. An honest list beats a submission that pretends they don't exist.

- **LinkedIn's bot defense is aggressive, and sessions get killed fast.**
  During development, a burst of ~12 endpoint-probe requests from a residential
  IP got the session flagged; LinkedIn then responded `302` to a redirect loop
  with `Set-Cookie: li_at=delete me` (a hard session kill) after only **1–2**
  further requests, even on a freshly-issued cookie from the same IP. The client
  detects this specific response and raises `SessionExpiredError` → `401`. There
  is **no auto-relogin**. Practical consequences:
  - keep request volume low (this app makes **one** Voyager call per profile);
  - expect to refresh cookies often;
  - a flagged IP stays hot for hours — the deployment IP matters, and a
    datacenter IP will likely be worse than residential.
- **`decorationId` version drift.** `FullProfileWithEntities-93` is hard-coded.
  When LinkedIn bumps it, the endpoint starts returning `302`/`4xx`. Fix: try
  adjacent versions or re-capture from a live session
  (`python -m scripts.dump_voyager <url>`), then update `PROFILE_DECORATION_ID`
  in [`app/voyager_client.py`](app/voyager_client.py).
- **Skills, certifications and languages are not returned.** The
  `FullProfileWithEntities-93` projection doesn't inline them; they sit behind
  separate `dash/profileSkills` / `dash/profileCertifications` /
  `dash/profileLanguages` calls. Fetching them would mean 3–4 extra requests per
  profile, which — given the point above — is not worth it. These lists come
  back `[]` with a warning. Adding them later is straightforward if request
  budget allows.
- **`connections` / `followers` are not returned** by this projection either
  (they need `dash/profiles` with a different decoration, or a `networkinfo`
  call). Currently always `null`.
- **Unofficial, undocumented API.** LinkedIn can change paths, `decorationId`s,
  entity `$type`s or field names at any time without notice. The parser is
  defensive so drift degrades individual fields; a whole empty section means
  re-capture and diff.
- **Verified against real responses, on a narrow sample.** The endpoint and
  parser were confirmed end-to-end against live `200` responses (e.g. the Bill
  Gates profile above is real output). Coverage of unusual profiles (no
  experience, non-Latin names, deactivated accounts, heavy visibility
  restrictions) has not been exhaustively tested.
- **Rate limiting is surfaced, not absorbed.** `429` / `999` become an HTTP
  `429` to the caller. No automatic backoff/retry.
- **Public-profile data only.** Fields LinkedIn gates on network distance/degree
  are not accounted for. You get roughly what *your logged-in session* sees on
  the profile page.
- **One endpoint.** Featured posts, recommendations, volunteering, projects,
  publications and full "Activity" live on other Voyager endpoints and aren't
  collected.

---

## Project layout

```
app/
  main.py            FastAPI app: routes, exception -> HTTP status mapping
  scraper.py         orchestrates client + parser (scrape_profile)
  voyager_client.py  httpx client for the dash/profiles endpoint; URL parsing;
                     typed errors incl. the session-kill redirect
  parser.py          REST.li `included` list (dash schema) -> LinkedInProfile
  models.py          Pydantic response schema
  auth.py            loads li_at / JSESSIONID cookies from env
scripts/
  dump_voyager.py    one careful request -> dump a real response + $type summary
  probe_endpoints.py the endpoint-discovery probe (how the dash endpoint was found)
tests/
  fixtures.py        synthetic dash-shaped `included` response
  test_parser.py     parser vs. that fixture (URN resolution, dateRange, Geo)
  test_api.py        endpoint wiring + exception -> status-code mapping
Dockerfile
render.yaml          Render blueprint
.env.example
```

---

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

16 tests, no network access required (the API tests monkeypatch the scraper).

To capture / re-verify a live response after a cookie refresh:

```bash
python -m scripts.dump_voyager "https://www.linkedin.com/in/<slug>/"
# writes dash_profile_raw.json (gitignored) + prints the $type breakdown
```

`scripts/probe_endpoints.py` fires a spaced-out sweep of candidate endpoints —
useful only when the primary endpoint breaks and you need to find its
replacement. It will get your session flagged; run it sparingly.
