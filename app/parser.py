"""
Voyager responses use the REST.li "included" convention: rather than one
nested JSON document, the API returns a flat list of typed entities
(Profile, Position, Education, Skill, Certification, Language, ...), each
tagged with a `$type` field. This module walks that list and reassembles it
into the clean schema defined in models.py.

NOTE ON FRAGILITY: this mapping was built from the well-documented public
shape of this endpoint (the same one several open-source LinkedIn API
wrappers rely on), not verified against a live response in this
environment. Field names occasionally drift when LinkedIn ships frontend
changes. Every extraction below is defensive (missing key -> None / skip)
so a schema drift degrades individual fields rather than crashing the
whole request — but if you see a section come back consistently empty,
capture a real response (see README "Debugging Voyager responses") and
diff the $type / field names against what's expected here.
"""

import logging
from typing import Any, Dict, List, Optional

from .models import (
    Certification,
    Education,
    Experience,
    Language,
    LinkedInProfile,
    ProfileImages,
    Skill,
)

logger = logging.getLogger("linkedin_api.parser")

TYPE_PROFILE = "identity.profile.Profile"
TYPE_POSITION = "identity.profile.Position"
TYPE_EDUCATION = "identity.profile.Education"
TYPE_SKILL = "identity.profile.Skill"
TYPE_CERTIFICATION = "identity.profile.Certification"
TYPE_LANGUAGE = "identity.profile.Language"


def _entities_of_type(included: List[Dict[str, Any]], suffix: str) -> List[Dict[str, Any]]:
    return [e for e in included if str(e.get("$type", "")).endswith(suffix)]


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


def _format_duration(time_period: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    if not time_period:
        return {"duration": None, "start": None, "end": None}
    start = _format_date(time_period.get("startDate"))
    end = _format_date(time_period.get("endDate"))
    if start and end:
        duration = f"{start} - {end}"
    elif start:
        duration = f"{start} - Present"
    else:
        duration = None
    return {"duration": duration, "start": start, "end": end}


def _best_image_url(picture_obj: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Profile/background pictures come back as a `vectorImage`-style object:
    a rootUrl plus a list of artifacts (different resolutions), each with a
    partial path segment. We take the largest available artifact.
    Real shape (approximately):
      {"displayImageReference": {"vectorImage": {
          "rootUrl": "https://media.licdn.com/dms/image/...",
          "artifacts": [{"width": 800, "fileIdentifyingUrlPathSegment": "..."}]
      }}}
    """
    if not picture_obj:
        return None
    vector = (picture_obj.get("displayImageReference") or {}).get("vectorImage") or picture_obj.get(
        "vectorImage"
    )
    if not vector:
        return None
    root = vector.get("rootUrl")
    artifacts = vector.get("artifacts") or []
    if not root or not artifacts:
        return None
    largest = max(artifacts, key=lambda a: a.get("width", 0))
    segment = largest.get("fileIdentifyingUrlPathSegment", "")
    return f"{root}{segment}" if segment else root


def parse_profile_view(raw: Dict[str, Any], profile_url: str, scraped_at: str) -> LinkedInProfile:
    warnings: List[str] = []
    included = raw.get("included", [])
    if not included:
        warnings.append(
            "Voyager response had no 'included' entities — the response "
            "shape may have changed, or this profile has restricted "
            "visibility for the current session."
        )

    profile_entities = _entities_of_type(included, TYPE_PROFILE)
    profile = profile_entities[0] if profile_entities else {}
    if not profile_entities:
        warnings.append("No Profile entity found in response.")

    first_name = profile.get("firstName", "")
    last_name = profile.get("lastName", "")
    name = f"{first_name} {last_name}".strip() or None

    location = profile.get("geoLocationName") or profile.get("locationName")

    images = ProfileImages(
        profile_photo_url=_best_image_url(profile.get("profilePicture")),
        background_photo_url=_best_image_url(profile.get("backgroundPicture")),
    )

    experience: List[Experience] = []
    for pos in _entities_of_type(included, TYPE_POSITION):
        d = _format_duration(pos.get("timePeriod"))
        experience.append(
            Experience(
                title=pos.get("title"),
                company=pos.get("companyName")
                or (pos.get("company") or {}).get("miniCompany", {}).get("name"),
                employment_type=pos.get("employmentType"),
                duration=d["duration"],
                start_date=d["start"],
                end_date=d["end"],
                location=pos.get("locationName"),
                description=pos.get("description"),
                company_logo_url=_best_image_url(
                    (pos.get("company") or {}).get("miniCompany", {}).get("logo")
                ),
            )
        )

    education: List[Education] = []
    for edu in _entities_of_type(included, TYPE_EDUCATION):
        d = _format_duration(edu.get("timePeriod"))
        education.append(
            Education(
                school=edu.get("schoolName"),
                degree=edu.get("degreeName"),
                field_of_study=edu.get("fieldOfStudy"),
                duration=d["duration"],
                start_date=d["start"],
                end_date=d["end"],
                description=edu.get("description"),
                school_logo_url=_best_image_url(edu.get("school", {}).get("logo")),
            )
        )

    skills: List[Skill] = []
    for sk in _entities_of_type(included, TYPE_SKILL):
        sk_name = sk.get("name")
        if sk_name:
            skills.append(
                Skill(name=sk_name, endorsement_count=sk.get("endorsementCount"))
            )

    certifications: List[Certification] = []
    for cert in _entities_of_type(included, TYPE_CERTIFICATION):
        d = _format_duration(cert.get("timePeriod"))
        certifications.append(
            Certification(
                name=cert.get("name"),
                issuing_organization=cert.get("authority"),
                issue_date=d["start"],
                credential_id=cert.get("licenseNumber"),
                credential_url=cert.get("url"),
            )
        )

    languages: List[Language] = []
    for lang in _entities_of_type(included, TYPE_LANGUAGE):
        lang_name = lang.get("name")
        if lang_name:
            languages.append(
                Language(name=lang_name, proficiency=lang.get("proficiency"))
            )

    if not experience:
        warnings.append("No experience entries parsed.")
    if not education:
        warnings.append("No education entries parsed.")

    return LinkedInProfile(
        profile_url=profile_url,
        name=name,
        headline=profile.get("headline"),
        location=location,
        about=profile.get("summary"),
        connections=str(profile.get("connections")) if profile.get("connections") else None,
        followers=str(profile.get("followersCount")) if profile.get("followersCount") else None,
        images=images,
        experience=experience,
        education=education,
        skills=skills,
        certifications=certifications,
        languages=languages,
        scraped_at=scraped_at,
        warnings=warnings,
    )
