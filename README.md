# LinkedIn Profile API

A hosted HTTPS API that takes a **LinkedIn profile URL** and returns most of
the profile-page information as structured JSON.

It is **purely reverse-engineered** — it calls LinkedIn's own web endpoints
directly over HTTP (`curl_cffi` with Chrome TLS/HTTP2 impersonation) with an
authenticated session cookie. **No browser, no headless automation, no
third-party scraping API.**

```
GET /api/profile?url=https://www.linkedin.com/in/<slug>/
```

## Live demo

Endpoint: **`https://linkedin-tross.onrender.com/api/profile?url=`** — append
any public LinkedIn profile URL.

```bash
curl "https://linkedin-tross.onrender.com/api/profile?url=https://www.linkedin.com/in/williamhgates/" | jq
```

Swap `williamhgates` for any profile you want — `.../in/<slug>/`. A plain
browser hit on that URL works too.

- Docs (Swagger): <https://linkedin-tross.onrender.com/docs>
- Health: <https://linkedin-tross.onrender.com/health>
- First hit after ~15 min idle takes ~50 s (Render free-tier cold start).
- A `401` means the LinkedIn session cookie needs a manual refresh — see
  [limitations](#known-limitations).

---

## Contents
- [Quick start](#quick-start)
- [Getting the LinkedIn cookie](#getting-the-linkedin-cookie)
- [Environment variables](#environment-variables)
- [API documentation](#api-documentation)
- [Approach](#approach)
- [Known limitations](#known-limitations)
- [Project layout](#project-layout)
- [Deployment](#deployment)
- [Development](#development)

---

## Quick start

Python 3.11+ (3.12 recommended).

```bash
git clone <this-repo> && cd linkedin-profile-api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then paste your cookie in — see below
uvicorn app.main:app --reload

curl "http://localhost:8000/api/profile?url=https://www.linkedin.com/in/williamhgates/" | jq
```

Swap in any public profile URL (`https://www.linkedin.com/in/<slug>/`) to test
a different person.

Docker:

```bash
docker build -t linkedin-profile-api .
docker run --rm --name linkedin_tross -p 8000:8000 --env-file .env linkedin-profile-api

# same test command — the container publishes on localhost:8000
curl "http://localhost:8000/api/profile?url=https://www.linkedin.com/in/williamhgates/" | jq
```

---

## Getting the LinkedIn cookie

The API does not log in for you — you log in once in a real browser and copy
the session cookie into an env var. (Why: automating the login form reliably
trips LinkedIn's checkpoints; copying a cookie doesn't.)

1. Log into <https://www.linkedin.com> in Chrome/Firefox. Prefer a **real,
   aged account** — brand-new accounts get challenged fast regardless.
2. DevTools → **Network** tab → reload the page.
3. Right-click any `www.linkedin.com` request → **Copy → Copy as cURL**.
4. From that cURL, take the **`-b '…'`** (or `-H 'cookie: …'`) value — one long
   line, ~15 `name=value;` pairs — and set it as **`LI_COOKIE_STRING`** in
   `.env`. The app parses `JSESSIONID` out of it for the CSRF header.
5. Don't click **Log out** afterwards — that invalidates the session. Just
   close the tab.

> Thin fallback: set only `LI_AT_COOKIE` + `LI_JSESSIONID_COOKIE` (both from
> the same login; read `li_at` from *Application → Cookies* since it's
> `HttpOnly`). More bot-like — prefer `LI_COOKIE_STRING`.

`.env` is git-ignored. `.env.example` documents every variable with no values.

---

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `LI_COOKIE_STRING` | **Yes** (preferred) | Full browser `cookie:` header (~15 cookies incl. the PerimeterX `_px3`). |
| `LI_AT_COOKIE` / `LI_JSESSIONID_COOKIE` | fallback | Used only if `LI_COOKIE_STRING` is unset. |
| `OUTBOUND_PROXY` | No (recommended for volume) | `http://user:pass@host:port` — routes the LinkedIn calls through a residential/mobile proxy. Datacenter IPs are lower-trust; in this project's testing the SDUI path still held from Render with **no** proxy, but adding one is the first fix if a cloud host starts returning `401`. Unset = direct (fine from a home IP). |
| `FETCH_DETAIL_CARDS` | No | `0` → return the top card only (1 request instead of 5). Default on. |
| `IMPERSONATE_TARGET` | No | `curl_cffi` TLS profile. Default `chrome136`. |
| `PORT` | No | Bind port (PaaS hosts inject it; default `8000`). |

---

## API documentation

### `GET /health`
`{ "status": "ok" }` — liveness for the platform.

### `GET /api/profile`

| Query param | Type | Required | Description |
|---|---|---|---|
| `url` | string | yes | Full profile URL, e.g. `https://www.linkedin.com/in/williamhgates/`. Query string / trailing slash are fine — only the `/in/<slug>` segment is used. |

**`200 OK`** — a `LinkedInProfile`. Every field is best-effort: anything not
confidently extracted is `null` / `[]`, and `warnings` says what was missing
rather than failing the request. Real output (Bill Gates, Aug 2026, image
URLs shortened):

```jsonc
{
  "profile_url": "https://www.linkedin.com/in/williamhgates/",
  "name": "Bill Gates",
  "headline": "Chair, Gates Foundation and Founder, Breakthrough Energy",
  "location": "Seattle, Washington, United States",
  "current_company": "Gates Foundation",
  "about": "Chair of the Gates Foundation. Founder of Breakthrough Energy. …",
  "connections": null,           // shown only for some viewer/degree combos
  "connection_degree": "3rd",
  "followers": "40,601,261",
  "website": null,
  "images": {
    "profile_photo_url": "https://media.licdn.com/dms/image/v2/.../profile-displayphoto-…_800_800/…",
    "background_photo_url": "https://media.licdn.com/dms/image/v2/.../profile-displaybackgroundimage-…_1400/…"
  },
  "experience": [
    { "title": "Co-chair",  "company": "Gates Foundation",    "duration": "2000 – Present", "start_date": "2000", "end_date": null, "location": null },
    { "title": "Founder",    "company": "Breakthrough Energy", "duration": "2015 – Present", "start_date": "2015", "end_date": null, "location": null },
    { "title": "Co-founder", "company": "Microsoft",           "duration": "1975 – Present", "start_date": "1975", "end_date": null, "location": null }
  ],
  "education": [
    { "school": "Harvard University", "degree": null, "duration": "1973 – 1975", "start_date": "1973", "end_date": "1975" },
    { "school": "Lakeside School",    "degree": null, "duration": null,          "start_date": null,   "end_date": null }
  ],
  "skills": [],                   // present with endorsement counts when LinkedIn exposes them
  "certifications": [],           // see limitations
  "languages": [],               // see limitations
  "scraped_at": "2026-08-30T00:00:00+00:00",
  "warnings": []
}
```

`name` / `headline` / `location` / `current_company` / `followers` / `images`
are server-rendered on the page and **reliable**. `about` / `experience` /
`education` / `skills` come from lazy detail calls and are **best-effort**.

**Errors** — shape `{ "error": "<message>", "detail": null }`:

| Status | When |
|---|---|
| `400` | `url` isn't a parseable LinkedIn profile URL |
| `401` | session cookie expired / flagged / killed, or redirected to the auth wall |
| `404` | LinkedIn has no profile for that slug |
| `422` | `url` query param missing |
| `429` | LinkedIn rate-limited / soft-blocked (`429` / `999`) |
| `500` | anything unexpected |

---

## Approach

### Why reverse-engineer the web endpoints (and not…)

| Option | Verdict |
|---|---|
| **LinkedIn's own web endpoints, called directly over HTTP** | **Chosen.** Satisfies "reverse-engineered, direct, no browser". |
| Headless browser + DOM scraping (Playwright/Selenium) | **Excluded by the brief.** No browser dependency exists in this repo. |
| Third-party scraper APIs (Proxycurl, PhantomBuster, …) | Rejected — not "reverse engineer / build". |
| Official LinkedIn OAuth API | Rejected — only exposes the *authenticated user's own* data. |

The only browser touch anywhere is a human logging in once to copy the cookie.

### What the site actually exposes (the reverse-engineering journey)

1. `/voyager/api/identity/profiles/{id}/profileView` — the endpoint every
   open-source wrapper uses — now returns **HTTP 410 Gone**.
2. `/voyager/api/identity/dash/profiles?…&decorationId=FullProfileWithEntities-*`
   — a newer REST.li endpoint — still returns data, but the current web app
   never calls it, so hitting it twice within minutes gets the session
   **killed** (`302` redirect loop + `Set-Cookie: li_at=delete me`), from any
   IP / account. Confirmed unusable, so **not shipped**.
3. The **current profile page is Server-Driven UI** (LinkedIn's "COMO"
   framework — React Server Components). This project reverse-engineers
   *that*, because those are the requests a real browser makes — they blend
   into normal traffic and the session survives.

### Request flow

```
URL ─▶ extract_public_identifier()                         (linkedin_http.py)
    ─▶ WebClient.fetch_profile_html(slug)  GET /in/<slug>/
    ─▶ parse_top_card(html, slug)                          (page_parser.py)
         name, headline, location, current_company, followers, degree,
         website, photos, fsd_profile id — from <title> + the
         window.__como_rehydration__ React-Flight blob in <script id="rehydrate-data">
    ─▶ WebClient.fetch_component() ×4      POST /flagship-web/rsc-action/actions/component
         componentId = …profileCardsAboveActivity            -> About
                       …profileCardsExperienceOnly            -> Experience
                       …profileCardsBelowActivityPart1WithoutExp  -> Education
                       …profileCardsBelowActivityPart7        -> Skills
    ─▶ parse_about / _experience / _education / _skills    (flight_parser.py)
    ─▶ LinkedInProfile JSON                                (main.py)
```

Each `rsc-action` POST sends the ~3 KB `clientArguments` body LinkedIn's
client sends (templated with the slug + profile id) and gets back a
React-Flight payload — newline-separated `<id>:<json>` rows. We pull the
ordered `"children":["…text…"]` leaves and split them on section landmarks
("About", "Experience", "Education", the `"… followers"` / `"Contact info"`
lines, `licdn` URLs) — never the hashed CSS class names, which churn.

Step 1 is the reliable core (always returns). Step 2 is best-effort: a blocked
card yields an empty section + a `warnings` entry, not a failed request.
`FETCH_DETAIL_CARDS=0` skips step 2 entirely.

### TLS / HTTP2 fingerprint

A plain Python HTTP client (`httpx`, `requests`) has a JA3/JA4 +
HTTP2-SETTINGS fingerprint that matches no browser — an independent bot
signal. All calls go through [`curl_cffi`](https://github.com/lexiforest/curl_cffi)
with `impersonate="chrome136"`, so the handshake matches Chrome.

---

## Known limitations

Honest list — these are inherent to unofficial access, not bugs to fix later.

- **The session cookie is a manually-managed secret with a short lifetime.**
  It expires or gets invalidated (password change, suspicious-activity flag,
  logging out elsewhere) and there is **no auto-relogin** — the request fails
  `401` with a "refresh the cookie" message.
- **Datacenter IPs are lower-trust — but not blocked.** The SDUI path has
  held up from Render's datacenter IP with only the full cookie string (no
  proxy) across this project's testing. It's still the weaker setup: a
  residential/mobile `OUTBOUND_PROXY` is the recommended hedge for sustained
  volume, and the first thing to add if a cloud host starts returning `401`.
  From a home IP no proxy is needed. No request throttling/backoff or
  account-pool is built in — that's what a production version would add.
  Community-reported sustainable rate on an aged account is ~100–300
  profiles/day, paced.
- **Experience / Education / Skills are best-effort.** They're parsed from
  rendered UI (React-Flight text leaves), not a clean data API. Ordinary
  roles, company-grouped roles and board positions parse correctly; unusual
  layouts (roles with no dates, heavy nesting, media attachments) can
  mis-group or drop an entry. It degrades to *empty/partial*, not
  confidently-wrong. The **top card is unaffected**.
- **Don't scrape your own profile with your own cookie.** LinkedIn serves a
  self-view (edit + analytics) layout; the scraper detects this, filters what
  it can, and adds a `warnings` note. Use a different account's cookie for a
  clean read of your own profile.
- **`certifications` and `languages` are always `[]`.** Their `rsc-action`
  card slot varies by profile and each is another request; left out to keep
  request volume (and flag risk) down. The response schema keeps the fields.
- **`skills`** comes from `…Part7`, whose contents vary by profile — the
  parser returns `[]` (rather than guessing) when that slot isn't the skills
  card, so some profiles with skills will show `skills: []`.
- **Component ids / body shape can change.** LinkedIn ships frontend releases
  often; if a card returns nothing, re-capture the request from a live
  session.
- **Public-profile data only** — roughly what your logged-in session sees on
  the page. No posts / recommendations / volunteering / projects.

---

## Project layout

```
app/
  main.py            FastAPI app — routes + exception → HTTP status mapping
  scraper.py         orchestrates: page → top card → 4 detail cards → merge
  web_client.py      curl_cffi client: GET /in/<slug>/ ; POST rsc-action cards
  page_parser.py     profile-page HTML → top card
  flight_parser.py   React-Flight payload → about / experience / education / skills
  linkedin_http.py   shared config, cookie loading, proxy, typed errors, URL parsing
  models.py          Pydantic response schema
  templates/
    rsc_component_body.json.tpl   captured rsc-action body, {VANITY}/{PROFILE_ID}
tests/
  test_page_parser.py    top card vs tests/captures/mini_profile.html
  test_flight_parser.py   sections vs real tests/captures/*.flight
  test_api.py             endpoint wiring + exception → status mapping
  captures/               real Flight card payloads + a mini HTML fixture
Dockerfile   render.yaml   .env.example
```

---

## Deployment

Ships a platform-agnostic **`Dockerfile`** (honours `$PORT`, binds
`0.0.0.0`) and a **`render.yaml`** blueprint.

**Render:** push to GitHub → dashboard → **New +** → **Blueprint** → pick the
repo → set `LI_COOKIE_STRING` when prompted (and `OUTBOUND_PROXY` if you have
one — optional; both `sync: false`, never in the repo) → deploy. Free tier
sleeps after ~15 min idle; a free uptime pinger on `/health` keeps it warm.

**Any other Docker host** (Fly.io, Railway, a VM): the `Dockerfile` is all you
need — set the same env vars.

---

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # 32 tests, no network (parsers run against committed captures)
```

To re-capture live card payloads after LinkedIn ships a change: open a profile
in a logged-in browser with DevTools → Network, and copy the
`rsc-action/actions/component` responses (and the `/in/<slug>/` document) into
`tests/captures/`.
