"""
Synthetic Voyager `profileView` response used by the parser tests.

This is hand-built to match the REST.li `included` shape parser.py expects
(a flat list of typed entities). It is NOT a captured real response — the
real one has more entities and more fields — but it exercises every branch
of parse_profile_view: profile summary, images, positions, education,
skills, certifications and languages.
"""

MOCK_PROFILE_VIEW = {
    "included": [
        {
            "$type": "com.linkedin.voyager.identity.profile.Profile",
            "firstName": "Ada",
            "lastName": "Lovelace",
            "headline": "Mathematician | Writing the first algorithm",
            "geoLocationName": "London, England, United Kingdom",
            "summary": "Fascinated by the Analytical Engine and what it could compute.",
            "profilePicture": {
                "displayImageReference": {
                    "vectorImage": {
                        "rootUrl": "https://media.licdn.com/dms/image/pp/",
                        "artifacts": [
                            {"width": 100, "fileIdentifyingUrlPathSegment": "100_100/x.jpg"},
                            {"width": 800, "fileIdentifyingUrlPathSegment": "800_800/x.jpg"},
                        ],
                    }
                }
            },
            "backgroundPicture": {
                "displayImageReference": {
                    "vectorImage": {
                        "rootUrl": "https://media.licdn.com/dms/image/bg/",
                        "artifacts": [
                            {"width": 1400, "fileIdentifyingUrlPathSegment": "1400_425/y.jpg"},
                        ],
                    }
                }
            },
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Position",
            "title": "Collaborator",
            "companyName": "Analytical Engine Project",
            "employmentType": "Full-time",
            "locationName": "London, United Kingdom",
            "description": "Translated and annotated Menabrea's memoir.",
            "timePeriod": {
                "startDate": {"month": 1, "year": 1842},
                "endDate": {"month": 12, "year": 1843},
            },
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Position",
            "title": "Independent Researcher",
            "companyName": "Self-employed",
            "timePeriod": {"startDate": {"month": 6, "year": 1843}},
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Education",
            "schoolName": "Private tutoring",
            "degreeName": "Mathematics & Science",
            "fieldOfStudy": "Mathematics",
            "timePeriod": {"startDate": {"year": 1833}, "endDate": {"year": 1840}},
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Skill",
            "name": "Analytical Engines",
            "endorsementCount": 42,
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Skill",
            "name": "Technical Writing",
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Certification",
            "name": "Certificate in Calculus",
            "authority": "Somerville",
            "licenseNumber": "CALC-1837",
            "url": "https://example.com/cert",
            "timePeriod": {"startDate": {"month": 3, "year": 1837}},
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Language",
            "name": "English",
            "proficiency": "NATIVE_OR_BILINGUAL",
        },
        {
            "$type": "com.linkedin.voyager.identity.profile.Language",
            "name": "French",
            "proficiency": "PROFESSIONAL_WORKING",
        },
    ]
}
