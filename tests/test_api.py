"""
Endpoint tests. `scrape_profile` is monkeypatched so nothing here touches
the network or needs a real cookie — we only check the HTTP wiring and the
exception -> status-code mapping in main.py.
"""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("LI_AT_COOKIE", "test-cookie")

from app import main  # noqa: E402
from app.models import LinkedInProfile  # noqa: E402
from app.voyager_client import (  # noqa: E402
    ProfileNotFoundError,
    SessionExpiredError,
    VoyagerRateLimitedError,
)

client = TestClient(main.app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_profile_ok(monkeypatch):
    async def fake_scrape(url):
        return LinkedInProfile(profile_url=url, name="Ada Lovelace", scraped_at="ts")

    monkeypatch.setattr(main, "scrape_profile", fake_scrape)
    r = client.get("/api/profile", params={"url": "https://www.linkedin.com/in/x/"})
    assert r.status_code == 200
    assert r.json()["name"] == "Ada Lovelace"


def test_missing_url_param():
    r = client.get("/api/profile")
    assert r.status_code == 422


@pytest.mark.parametrize(
    "exc, status",
    [
        (ValueError("bad url"), 400),
        (SessionExpiredError("expired"), 401),
        (ProfileNotFoundError("nope"), 404),
        (VoyagerRateLimitedError("slow down"), 429),
        (RuntimeError("boom"), 500),
    ],
)
def test_exception_mapping(monkeypatch, exc, status):
    async def fake_scrape(url):
        raise exc

    monkeypatch.setattr(main, "scrape_profile", fake_scrape)
    r = client.get("/api/profile", params={"url": "https://www.linkedin.com/in/x/"})
    assert r.status_code == status
    assert "error" in r.json()
