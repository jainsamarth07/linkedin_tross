import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .models import ErrorResponse, LinkedInProfile
from .scraper import scrape_profile
from .voyager_client import (
    ProfileNotFoundError,
    SessionExpiredError,
    VoyagerRateLimitedError,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("linkedin_api.main")

app = FastAPI(
    title="LinkedIn Profile API",
    description=(
        "Accepts a public LinkedIn profile URL and returns structured "
        "profile data by calling LinkedIn's internal Voyager API with an "
        "authenticated session. See README.md for setup and limitations."
    ),
    version="1.0.0",
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get(
    "/api/profile",
    response_model=LinkedInProfile,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def get_profile(
    url: str = Query(
        ...,
        description="Full LinkedIn profile URL, e.g. https://www.linkedin.com/in/johndoe/",
    )
):
    try:
        profile = await scrape_profile(url)
        return profile
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SessionExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except VoyagerRateLimitedError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        logger.exception("Unhandled error scraping profile %s", url)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=exc.detail).model_dump(),
    )
