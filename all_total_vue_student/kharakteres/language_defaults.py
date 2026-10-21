"""Internal core language candidates and legacy aliases; not the full UI catalog.

The selectable Korean-named catalog lives in language_catalog.py. These 13 entries
only preserve model candidates, known dictionary sections and compatibility aliases."""

# Core LLM candidates and known dictionary sections share canonical catalog codes.
LANGUAGES = [
    {"code": "ko", "name": "한국어", "family": "현대 언어"},
    {"code": "en", "name": "영어", "family": "현대 언어"},
    {"code": "ja", "name": "일본어", "family": "현대 언어"},
    {"code": "zh", "name": "중국어", "family": "현대 언어"},
    {"code": "fr", "name": "프랑스어", "family": "현대 언어"},
    {"code": "de", "name": "독일어", "family": "현대 언어"},
    {"code": "es", "name": "스페인어", "family": "현대 언어"},
    {"code": "ar", "name": "아랍어", "family": "현대 언어"},
    {"code": "it", "name": "이탈리아어", "family": "현대 언어"},
    {"code": "la", "name": "라틴어", "family": "고전 언어"},
    {"code": "grc", "name": "고전 그리스어", "family": "고전 언어"},
    {"code": "sa", "name": "산스크리트어", "family": "고전 언어"},
    {"code": "cu", "name": "고대 교회 슬라브어", "family": "고전 언어"},
]
# Keep section keys independent of the complete selectable language list.
LANGUAGE_SECTIONS = {
    "ko": "Korean", "en": "English", "ja": "Japanese", "zh": "Chinese",
    "fr": "French", "de": "German", "es": "Spanish", "ar": "Arabic",
    "it": "Italian", "la": "Latin", "grc": "Ancient Greek", "sa": "Sanskrit",
    "cu": "Old Church Slavonic",
}
LANGUAGE_ALIASES = {
    "고대 그리스어": "grc", "고전 라틴어": "la", "산스크리트": "sa",
    "고대교회슬라브어": "cu", "고교회 슬라브어": "cu", "고교회슬라브어": "cu",
    "고대 교회 슬라브어": "cu", "Old Church Slavic": "cu", "chu": "cu", "OCS": "cu",
    "이태리어": "it", "Italiano": "it", "ita": "it",
}


def canonical_basic(value):
    value = value.strip()
    aliases = {l["name"].casefold(): l["code"] for l in LANGUAGES}
    aliases.update({name.casefold(): code for code, name in LANGUAGE_SECTIONS.items()})
    aliases.update({code: code for code in LANGUAGE_SECTIONS})
    aliases.update({alias.casefold(): code for alias, code in LANGUAGE_ALIASES.items()})
    return aliases.get(value.casefold(), value)

