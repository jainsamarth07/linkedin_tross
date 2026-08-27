# LinkedIn Profile API

A hosted HTTPS API that accepts a **public LinkedIn profile URL** and returns
most of the information on the profile page as structured JSON.

It works by calling LinkedIn's own internal **Voyager** API — the undocumented
REST endpoints (`/voyager/api/...`) that linkedin.com's web frontend calls when
you browse a profile — authenticated with a copied session cookie.

```
GET /api/profile?url=https://www.linkedin.com/in/<slug>/
```

---

## Contents
- [Quick start (local)](#quick-start-local)
- [Getting your LinkedIn session cookie](#getting-your-linkedin-session-cookie)
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
# edit .env and paste in your LI_AT_COOKIE (see next section)

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

## Getting your LinkedIn session cookie

This API does **not** log in for you. You log in once in a normal browser and
copy the resulting session cookie into an environment variable. (Rationale in
[Approach](#approach--design-decisions).)

1. **Prefer a secondary / throwaway LinkedIn account.** Automated use of a
   session can get it flagged or rate-limited; don't risk your primary account.
2. Log into <https://www.linkedin.com> in Chrome or Firefox as normal.
3. Open DevTools (`Cmd+Option+I` / `Ctrl+Shift+I`):
   - **Chrome:** *Application* tab → *Storage* → *Cookies* → `https://www.linkedin.com`
   - **Firefox:** *Storage* tab → *Cookies* → `https://www.linkedin.com`
4. Copy the **`li_at`** cookie's *Value* (a ~200-character string) →
   `LI_AT_COOKIE` in your `.env`.
5. *(Optional, recommended)* Copy the **`JSESSIONID`** cookie's *Value*
   (looks like `"ajax:1234567890123456789"`, quotes included) →
   `LI_JSESSIONID_COOKIE`. It is used to build the `csrf-token` header Voyager
   expects; some endpoints are stricter about this than others.
6. **Do not click "Log out"** in that browser afterwards — logging out
   invalidates the cookie server-side. Just close the tab. `li_at` otherwise
   stays valid for up to roughly a year.

> `li_at` is an `HttpOnly` cookie, so `document.cookie` in the console will not
> show it — the Application/Storage tab is the only way to read it.

### Environment variables

| Variable                | Required | Purpose |
|-------------------------|----------|---------|
| `LI_AT_COOKIE`          | **Yes**  | LinkedIn session cookie. The app refuses to start a request without it. |
| `LI_JSESSIONID_COOKIE`  | No       | Supplies the `csrf-token` header. Recommended. |
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
| `url`       | string | yes      | Full profile URL, e.g. `https://www.linkedin.com/in/williamhgates/`. Query params and trailing slash are fine; the `/in/<slug>` segment is what matters. |

#### Success — `200 OK`

Returns a `LinkedInProfile` object. Every field is best-effort: anything the
parser could not confidently extract comes back as `null` (or an empty list),
and `warnings` explains what was missing rather than failing the request.

```jsonc
{
  "profile_url": "https://www.linkedin.com/in/williamhgates/",
  "name": "Bill Gates",
  "headline": "Chair, Gates Foundation and founder of Breakthrough Energy",
  "location": "Seattle, Washington, United States",
  "about": "Co-chair of the Bill & Melinda Gates Foundation. ...",
  "connections": "12",
  "followers": "35000000",
  "images": {
    "profile_photo_url": "https://media.licdn.com/dms/image/.../profile.jpg",
    "background_photo_url": "https://media.licdn.com/dms/image/.../cover.jpg"
  },
  "experience": [
    {
      "title": "Co-founder",
      "company": "Microsoft",
      "employment_type": null,
      "duration": "01/1975 - Present",
      "start_date": "01/1975",
      "end_date": null,
      "location": null,
      "description": null,
      "company_logo_url": "https://media.licdn.com/dms/image/.../logo.png"
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
      "school_logo_url": null
    }
  ],
  "skills": [
    { "name": "Philanthropy", "endorsement_count": null }
  ],
  "certifications": [
    {
      "name": "Example Certification",
      "issuing_organization": "Example Body",
      "issue_date": "06/2020",
      "credential_id": "ABC-123",
      "credential_url": "https://example.com/verify"
    }
  ],
  "languages": [
    { "name": "English", "proficiency": "NATIVE_OR_BILINGUAL" }
  ],
  "scraped_at": "2026-08-27T12:00:00+00:00",
  "warnings": []
}
```

#### Errors

All errors share the shape `{ "error": "<message>", "detail": null }`.

| Status | When | What to do |
|--------|------|------------|
| `400`  | The `url` isn't a parseable LinkedIn profile URL. | Fix the URL. |
| `401`  | Session cookie is expired/invalid, or Voyager returned 401/403 / redirected to the auth wall. | Refresh `LI_AT_COOKIE` (and `LI_JSESSIONID_COOKIE`). |
| `404`  | LinkedIn returned no profile for that slug. | Check the slug exists / is public. |
| `422`  | The `url` query param is missing entirely. | Provide `?url=...`. |
| `429`  | LinkedIn rate-limited or soft-blocked the request (HTTP `429` or LinkedIn's `999`). | Back off and retry later. There is no automatic retry. |
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
   `LI_JSESSIONID_COOKIE` (they are declared `sync: false`, so Render prompts
   for them and never stores them in the repo).
4. Deploy. You get a public `https://<name>.onrender.com` URL.

**Cold starts:** Render's free web service spins down after ~15 minutes idle and
takes ~50 s to wake on the next request. For a low-traffic demo that's usually
fine; if it matters, point a free uptime pinger (cron-job.org, UptimeRobot) at
`/health` every 10 minutes, or move to a host without scale-to-zero.

### Any other Docker host (Fly.io, Railway, a VM, …)

The `Dockerfile` is all you need — it honours `$PORT` and binds `0.0.0.0`.
Just set the same environment variables. For Fly.io, `fly launch` will detect
the Dockerfile; set `min_machines_running = 1` in `fly.toml` if you want to
avoid scale-to-zero.

---

## Approach & design decisions

### Why the Voyager internal API

Four options were considered:

| Option | Verdict |
|--------|---------|
| **LinkedIn's internal Voyager API** (`/voyager/api/...`) | **Chosen.** It's literally "the LinkedIn API" the brief asks to reverse-engineer. Authenticated with a session cookie, it returns clean structured JSON directly — no HTML parsing. |
| Authenticated headless browser + DOM scraping (Playwright) | Considered as a hedge. Rejected: more brittle to HTML/class-name changes, heavier, slower, and building both wasn't worth it. |
| Third-party scraper APIs (Proxycurl, PhantomBuster, …) | Rejected: doesn't satisfy "build a hosted API" / "reverse engineer". |
| Official LinkedIn OAuth API | Rejected: only exposes the *authenticated user's own* data, not arbitrary third-party profiles. |

### Why a copied cookie instead of automated login

Driving LinkedIn's username/password form with a headless browser reliably trips
LinkedIn's bot defenses (CAPTCHA / email or phone "checkpoints") because from an
unrecognised datacenter it looks exactly like credential stuffing. That risks
locking the account.

Instead: log in **once, manually, in a real browser**, copy the `li_at` session
cookie into an environment variable, and replay it on every API call. This is
documented in [`app/auth.py`](app/auth.py). The trade-off is that the cookie is
a manually-managed secret with a finite lifetime — see limitations.

### How a Voyager response becomes the schema

`profileView` returns a REST.li **`included`** list: not one nested document but
a flat array of typed entities (`$type` ending in `.Profile`, `.Position`,
`.Education`, `.Skill`, `.Certification`, `.Language`), cross-referenced by URN.
[`app/parser.py`](app/parser.py) walks that list, filters by `$type`, and
reassembles it into the `LinkedInProfile` model. Every field read is a defensive
`.get()` chain: **schema drift degrades one field to `null`, it does not crash
the request** — and the `warnings` array reports what was missing.

### Request flow

```
URL ──▶ extract_public_identifier()   (app/voyager_client.py)
     ──▶ VoyagerClient.get_profile_view()  → GET /voyager/api/identity/profiles/{id}/profileView
     ──▶ parse_profile_view()              (app/parser.py)
     ──▶ LinkedInProfile JSON              (app/main.py)
```

---

## Known limitations

These are real. A short honest list beats a submission that pretends they don't
exist.

- **Session cookie lifetime.** `LI_AT_COOKIE` eventually expires or gets
  invalidated (password change, "suspicious activity" flag, logging out
  elsewhere). There is **no auto-relogin** — the request fails with `401` and a
  message telling you to refresh the cookie.
- **Unofficial, undocumented API.** LinkedIn can change Voyager's endpoint paths
  or entity field names at any time without notice. When a section starts coming
  back empty, re-capture a real response (`python -m scripts.dump_voyager <url>`)
  and diff the `$type` / field names against `app/parser.py`.
- **Live verification still pending.** The endpoint path, required headers, and
  `included` field names (`firstName`, `geoLocationName`,
  `timePeriod.startDate.month/year`, …) were built from the well-known public
  shape of this API and are covered by unit tests against a **synthetic** mock
  response — they have **not yet been confirmed against a live account** in this
  repo's current state. First task once a real cookie is available: run
  `scripts/dump_voyager.py` and reconcile any drift. The example response in
  this README is illustrative, not a captured response.
- **Rate limiting is surfaced, not absorbed.** LinkedIn's `429` / `999`
  soft-block becomes an HTTP `429` to the caller. There is no automatic
  backoff/retry or request throttling — that could be added.
- **Profile images are the least-certain mapping.** `_best_image_url()` in
  `app/parser.py` assumes a `vectorImage` / `artifacts` (rootUrl + path segment)
  shape. It's the part most likely to need adjustment against a real response.
- **Public-profile data only.** Fields LinkedIn gates on network distance/degree,
  and anything behind an additional access wall, are not accounted for. What you
  get back approximates what *your logged-in session* can see on the profile
  page.
- **Datacenter IP reputation.** LinkedIn soft-blocks cloud IP ranges more
  aggressively than residential ones, so a deployed instance may see more `429`s
  than local runs. Outbound proxying would mitigate this but is out of scope.
- **One endpoint.** Only `profileView` is called. Some profile-page data
  (featured posts, recommendations, full "Activity") lives on other Voyager
  endpoints and isn't collected.

---

## Project layout

```
app/
  main.py            FastAPI app: routes, exception -> HTTP status mapping
  scraper.py         orchestrates client + parser (scrape_profile)
  voyager_client.py  httpx client for Voyager; URL parsing; typed errors
  parser.py          REST.li `included` list  ->  LinkedInProfile
  models.py          Pydantic response schema
  auth.py            loads cookies from env
scripts/
  dump_voyager.py    dev helper: dump a real response for field-name diffing
tests/
  test_parser.py     parser vs. synthetic Voyager response
  test_api.py        endpoint wiring + status-code mapping
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

17 tests, no network access required (the API tests monkeypatch the scraper).

To verify against a live profile once you have a cookie:

```bash
python -m scripts.dump_voyager "https://www.linkedin.com/in/<slug>/"
```
