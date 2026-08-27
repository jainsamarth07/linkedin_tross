"""
Synthetic Voyager `identity/dash/profiles` response for the parser tests.

Hand-built to match the REST.li `included` shape observed in a real
Aug-2026 response: a flat entity list, star-prefixed URN refs
(`*company`, `*school`, `*geo`) pointing at sibling entities, `dateRange`
with `Date` sub-objects, `multiLocale*` maps. Trimmed to what
`parse_profile` reads.
"""

PROFILE_ID = "ACoAAATEST00000000000000000000000000000"

MOCK_DASH_PROFILE = {
    "data": {
        "entityUrn": "urn:li:collectionResponse:test",
        "*elements": [f"urn:li:fsd_profile:{PROFILE_ID}"],
        "$type": "com.linkedin.restli.common.CollectionResponse",
    },
    "included": [
        {
            "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
            "entityUrn": f"urn:li:fsd_profile:{PROFILE_ID}",
            "firstName": "Ada",
            "lastName": "Lovelace",
            "headline": "Mathematician | First algorithm",
            "summary": "Fascinated by the Analytical Engine.",
            "publicIdentifier": "ada-lovelace",
            "locationName": None,
            "geoLocation": {"*geo": "urn:li:fsd_geo:555"},
            "profilePicture": {
                "displayImageReference": {
                    "vectorImage": {
                        "rootUrl": "https://media.licdn.com/dms/image/pp/",
                        "artifacts": [
                            {"width": 100, "fileIdentifyingUrlPathSegment": "100/a.jpg"},
                            {"width": 800, "fileIdentifyingUrlPathSegment": "800/a.jpg"},
                        ],
                    }
                }
            },
            "backgroundPicture": {
                "displayImageReference": {
                    "vectorImage": {
                        "rootUrl": "https://media.licdn.com/dms/image/bg/",
                        "artifacts": [
                            {"width": 1400, "fileIdentifyingUrlPathSegment": "1400/b.jpg"},
                        ],
                    }
                }
            },
        },
        {
            "$type": "com.linkedin.voyager.dash.common.Geo",
            "entityUrn": "urn:li:fsd_geo:555",
            "defaultLocalizedName": "London, England, United Kingdom",
        },
        {
            "$type": "com.linkedin.voyager.dash.identity.profile.Position",
            "entityUrn": f"urn:li:fsd_profilePosition:({PROFILE_ID},1)",
            "title": "Collaborator",
            "companyName": "Analytical Engine Project",
            "multiLocaleTitle": {"en_US": "Collaborator"},
            "description": "Annotated Menabrea's memoir.",
            "*company": "urn:li:fsd_company:111",
            "dateRange": {
                "start": {"month": 1, "year": 1842},
                "end": {"month": 12, "year": 1843},
            },
        },
        {
            "$type": "com.linkedin.voyager.dash.identity.profile.Position",
            "entityUrn": f"urn:li:fsd_profilePosition:({PROFILE_ID},2)",
            "title": "Independent Researcher",
            "multiLocaleCompanyName": {"en_US": "Self-employed"},
            "dateRange": {"start": {"year": 1843}},
        },
        {
            "$type": "com.linkedin.voyager.dash.organization.Company",
            "entityUrn": "urn:li:fsd_company:111",
            "name": "Analytical Engine Project",
            "url": "https://www.linkedin.com/company/analytical-engine/",
            "logo": {
                "vectorImage": {
                    "rootUrl": "https://media.licdn.com/dms/image/co/",
                    "artifacts": [
                        {"width": 200, "fileIdentifyingUrlPathSegment": "200/c.png"},
                    ],
                }
            },
        },
        {
            "$type": "com.linkedin.voyager.dash.identity.profile.Education",
            "entityUrn": f"urn:li:fsd_profileEducation:({PROFILE_ID},1)",
            "schoolName": "Private tutoring",
            "degreeName": "Mathematics & Science",
            "fieldOfStudy": "Mathematics",
            "description": None,
            "*school": "urn:li:fsd_school:222",
            "dateRange": {"start": {"year": 1833}, "end": {"year": 1840}},
        },
        {
            "$type": "com.linkedin.voyager.dash.organization.School",
            "entityUrn": "urn:li:fsd_school:222",
            "name": "Private tutoring",
            "url": "https://www.linkedin.com/school/tutoring/",
            "logo": {
                "vectorImage": {
                    "rootUrl": "https://media.licdn.com/dms/image/sc/",
                    "artifacts": [
                        {"width": 200, "fileIdentifyingUrlPathSegment": "200/d.png"},
                    ],
                }
            },
        },
    ],
}
