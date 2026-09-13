"""Single source of truth for supported programme volumes.

The table is deliberately explicit: a credit total is not inferred from an
integer number of years for every postgraduate track (90-credit master
programmes are 1.5 years / 3 semesters).
"""

REGULATORY_PROFILES = {
    "KZ": "KZ_GOSO_2026",
    "INTERNATIONAL": "INTERNATIONAL_GENERIC",
}

PROGRAM_PROFILES = [
    {"education_level": "bachelor", "track": "standard", "jurisdiction": "KZ", "regulatory_profile": "KZ_GOSO_2026", "credits": [240], "semesters": [8]},
    {"education_level": "bachelor", "track": "standard", "jurisdiction": "INTERNATIONAL", "regulatory_profile": "INTERNATIONAL_GENERIC", "credits": [180, 240, 300, 360], "semesters": [6, 8, 10, 12]},
    {"education_level": "master", "track": "scientific_pedagogical", "jurisdiction": "KZ", "regulatory_profile": "KZ_GOSO_2026", "credits": [120], "semesters": [4]},
    # KZ ГОСО: profile master's programmes are 60 credits minimum; the
    # 1.5-year route is 90 credits and capped at 110. 120 belongs to the
    # scientific-pedagogical profile.
    {"education_level": "master", "track": "professional", "jurisdiction": "KZ", "regulatory_profile": "KZ_GOSO_2026", "credits": [60, 90], "semesters": [2, 3]},
    {"education_level": "master", "track": "scientific_pedagogical", "jurisdiction": "INTERNATIONAL", "regulatory_profile": "INTERNATIONAL_GENERIC", "credits": [60, 90, 120], "semesters": [2, 3, 4]},
    {"education_level": "master", "track": "professional", "jurisdiction": "INTERNATIONAL", "regulatory_profile": "INTERNATIONAL_GENERIC", "credits": [60, 90, 120], "semesters": [2, 3, 4]},
    {"education_level": "doctorate", "track": "scientific_pedagogical", "jurisdiction": "KZ", "regulatory_profile": "KZ_GOSO_2026", "credits": [180], "semesters": [6]},
    {"education_level": "doctorate", "track": "professional", "jurisdiction": "KZ", "regulatory_profile": "KZ_GOSO_2026", "credits": [180], "semesters": [6]},
    {"education_level": "doctorate", "track": "scientific_pedagogical", "jurisdiction": "INTERNATIONAL", "regulatory_profile": "INTERNATIONAL_GENERIC", "credits": [180], "semesters": [6]},
    {"education_level": "doctorate", "track": "professional", "jurisdiction": "INTERNATIONAL", "regulatory_profile": "INTERNATIONAL_GENERIC", "credits": [180], "semesters": [6]},
]


def profile_for(constraints: dict) -> dict | None:
    level = str(constraints.get("education_level") or "").lower()
    track = str(constraints.get("master_track") or constraints.get("doctorate_track") or "scientific_pedagogical").lower()
    if level == "bachelor":
        track = "standard"
    if track in {"profile", "specialized", "профильная"}:
        track = "professional"
    jurisdiction = str(constraints.get("jurisdiction") or "INTERNATIONAL").upper()
    regulatory_profile = str(constraints.get("regulatory_profile") or REGULATORY_PROFILES.get(jurisdiction) or "").upper()
    credits, semesters = int(constraints.get("total_credits") or 0), int(constraints.get("total_semesters") or 0)
    for profile in PROGRAM_PROFILES:
        if (profile["education_level"], profile["track"], profile["jurisdiction"], profile["regulatory_profile"]) == (level, track, jurisdiction, regulatory_profile) and (credits, semesters) in zip(profile["credits"], profile["semesters"]):
            return profile
    return None
