"""Conservative identity for reviewed catalogue spelling/version aliases.

This is not fuzzy semantic deduplication. Unreviewed subjects and language
levels retain their identity; source titles are never rewritten.
"""

import re
import unicodedata


def discipline_identity(item: dict) -> str:
    title = " ".join(unicodedata.normalize("NFKC", str(item.get("title") or "")).casefold().split())
    title = title.rstrip(". ")
    # These complete generic course names describe the same professional
    # foreign-language unit. Named languages and numbered levels do not match.
    base = re.sub(r"\s*\(на английском языке\)$", "", title).strip()
    base = re.sub(r"\s*_профиль$", "", base).strip()
    # Apply confusable folding only for lookup in the reviewed alias set.
    # Never transliterate arbitrary course names or their numbered levels.
    alias_lookup = base.translate(str.maketrans({
        "o": "о", "p": "р", "a": "а", "c": "с", "e": "е", "x": "х",
    }))
    aliases = {
        "иностранный язык (профессиональный)",
        "иностранный язык (профессинальный)",
        "профессиональный иностранный язык",
    }
    if alias_lookup in aliases:
        return "reviewed:professional-foreign-language"
    return title
