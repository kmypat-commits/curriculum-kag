from app.services.language import epvo_payload_suffix, normalize_language


def test_normalize_language_accepts_kazakh_aliases_and_fallbacks():
    assert normalize_language("kz") == "kk"
    assert normalize_language("kazakh") == "kk"
    assert normalize_language("ENG") == "en"
    assert normalize_language("unknown") == "ru"


def test_epvo_payload_suffix_uses_normalized_language():
    assert epvo_payload_suffix("kz") == "Kz"
    assert epvo_payload_suffix("kk") == "Kz"
    assert epvo_payload_suffix("en") == "En"
    assert epvo_payload_suffix(None) == "Ru"
