"""
Turns a Voyager `identity/dash/profiles` response into the clean schema in
models.py.

The response uses the REST.li "included" convention: a flat list of typed
entities (`$type`), cross-referenced by `entityUrn`. Star-prefixed fields
(`*company`, `*school`, `*geo`) hold a URN that points at another entity in
the same `included` list; `_Resolver` does that lookup.

Entity `$type`s we care about (all under
`com.linkedin.voyager.dash.`):
  identity.profile.Profile      - the summary card
  identity.profile.Position     - one row of Experience
  identity.profile.Education    - one row of Education
  organization.Company          - employer (name, logo, url)
  organization.School           - school (name, logo, url)
  common.Geo                    - a resolved location string

FRAGILITY: field names here were verified against a live response
(Aug 2026) but LinkedIn drifts them without notice. Every read is a
defensive `.get()` chain so drift degrades one field to `null` and records
a note in `warnings` rather than crashing the request. If a whole section
comes back empty, re-capture with `python -m scripts.dump_voyager <url>`
and diff `$type` / keys against this file.

NOT in this response (decoration FullProfileWithEntities-93 does not inline
them): skills, certifications, languages. They live behind separate
`dash/profileSkills` / `dash/profileCertifications` / `dash/profileLanguages`
calls; fetching them would mean extra requests per profile, which we avoid
to keep LinkedIn's bot-defenses calm. Those lists come back empty with a
warning.
"""

import logging
from typing import Any, Dict, List, Optional

from .models import (
    Education,
    Experience,
    LinkedInProfile,
    ProfileImages,
)

logger = logging.getLogger("linkedin_api.parser")

T_PROFILE = "identity.profile.Profile"
T_POSITION = "identity.profile.Position"
T_EDUCATION = "identity.profile.Education"
T_COMPANY = "organization.Company"
T_SCHOOL = "organization.School"
T_GEO = "common.Geo"


class _Resolver:
    """Look entities up by URN within one `included` list."""

    def __init__(self, included: List[Dict[str, Any]]):
        self._by_urn: Dict[str, Dict[str, Any]] = {}
        for e in included:
            urn = e.get("entityUrn")
            if urn:
                self._by_urn[urn] = e

    def get(self, urn: Optional[str]) -> Dict[str, Any]:
        if not urn:
            return {}
        return self._by_urn.get(urn, {})

    def of_type(self, included: List[Dict[str, Any]], suffix: str) -> List[Dict[str, Any]]:
        return [e for e in included if str(e.get("$type", "")).endswith(suffix)]


def _localized(entity: Dict[str, Any], field: str) -> Optional[str]:
    """
    Prefer the plain scalar field; fall back to the first value of the
    matching `multiLocale<Field>` map (e.g. multiLocaleTitle -> {"en_US": ...}).
    """
    val = entity.get(field)
    if not val:
        multi = entity.get("multiLocale" + field[:1].upper() + field[1:])
        if isinstance(multi, dict) and multi:
            val = next(iter(multi.values()))
    if isinstance(val, str):
        val = val.strip()
    return val or None


def _format_date(date_obj: Optional[Dict[str, Any]]) -> Optional[str]:
    if not date_obj:
        return None
    month = date_obj.get("month")
    year = date_obj.get("year")
    if year and month:
        return f"{month:02d}/{year}"
    if year:
        return str(year)
    return None


def _format_date_range(date_range: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    if not date_range:
        return {"duration": None, "start": None, "end": None}
    start = _format_date(date_range.get("start"))
    end = _format_date(date_range.get("end"))
    if start and end:
        duration = f"{start} - {end}"
    elif start:
        duration = f"{start} - Present"
    else:
        duration = None
    return {"duration": duration, "start": start, "end": end}


def _best_image_url(picture_obj: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Picture objects are a `vectorImage` (rootUrl + resolution artifacts),
    sometimes wrapped in `displayImageReference`. Return the largest
    artifact's full URL.
    """
    if not picture_obj:
        return None
    vector = (picture_obj.get("displayImageReference") or {}).get(
        "vectorImage"
    ) or picture_obj.get("vectorImage")
    if not vector:
        return None
    root = vector.get("rootUrl")
    artifacts = vector.get("artifacts") or []
    if not root or not artifacts:
        return None
    largest = max(artifacts, key=lambda a: a.get("width", 0))
    segment = largest.get("fileIdentifyingUrlPathSegment", "")
    return f"{root}{segment}" if segment else root


def _company_logo(resolver: _Resolver, entity: Dict[str, Any]) -> Optional[str]:
    company = resolver.get(entity.get("*company") or entity.get("companyUrn"))
    return _best_image_url(company.get("logo")) if company else None


def _location_string(resolver: _Resolver, profile: Dict[str, Any]) -> Optional[str]:
    geo_ref = profile.get("geoLocation") or {}
    geo = resolver.get(geo_ref.get("*geo") or geo_ref.get("geoUrn"))
    if geo.get("defaultLocalizedName"):
        return geo["defaultLocalizedName"]
    # older/leaner shapes
    return profile.get("locationName") or (profile.get("location") or {}).get(
        "countryCode"
    )


def parse_profile(raw: Dict[str, Any], profile_url: str, scraped_at: str) -> LinkedInProfile:
    warnings: List[str] = []
    included = raw.get("included", [])
    if not included:
        warnings.append(
            "Voyager response had no 'included' entities — the response "
            "shape may have changed, or this profile is not visible to the "
            "current session."
        )

    resolver = _Resolver(included)

    profile_entities = resolver.of_type(included, T_PROFILE)
    profile = profile_entities[0] if profile_entities else {}
    if not profile_entities:
        warnings.append("No Profile entity found in response.")

    name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or None

    images = ProfileImages(
        profile_photo_url=_best_image_url(profile.get("profilePicture")),
        background_photo_url=_best_image_url(profile.get("backgroundPicture")),
    )

    experience: List[Experience] = []
    for pos in resolver.of_type(included, T_POSITION):
        d = _format_date_range(pos.get("dateRange"))
        experience.append(
            Experience(
                title=_localized(pos, "title"),
                company=_localized(pos, "companyName"),
                employment_type=_localized(pos, "employmentType"),
                duration=d["duration"],
                start_date=d["start"],
                end_date=d["end"],
                location=_localized(pos, "locationName"),
                description=_localized(pos, "description"),
                company_logo_url=_company_logo(resolver, pos),
            )
        )

    education: List[Education] = []
    for edu in resolver.of_type(included, T_EDUCATION):
        d = _format_date_range(edu.get("dateRange"))
        school = resolver.get(edu.get("*school") or edu.get("schoolUrn"))
        education.append(
            Education(
                school=_localized(edu, "schoolName") or school.get("name"),
                degree=_localized(edu, "degreeName"),
                field_of_study=_localized(edu, "fieldOfStudy"),
                duration=d["duration"],
                start_date=d["start"],
                end_date=d["end"],
                description=_localized(edu, "description"),
                school_logo_url=_best_image_url(school.get("logo")),
            )
        )

    if not experience:
        warnings.append("No experience entries parsed.")
    if not education:
        warnings.append("No education entries parsed.")
    warnings.append(
        "Skills, certifications and languages are not included by this "
        "endpoint's projection and are returned empty (see README limitations)."
    )

    return LinkedInProfile(
        profile_url=profile_url,
        name=name,
        headline=profile.get("headline"),
        location=_location_string(resolver, profile),
        about=profile.get("summary"),
        connections=None,
        followers=None,
        images=images,
        experience=experience,
        education=education,
        skills=[],
        certifications=[],
        languages=[],
        scraped_at=scraped_at,
        warnings=warnings,
    )


# Back-compat alias: the module used to expose parse_profile_view.
parse_profile_view = parse_profile
