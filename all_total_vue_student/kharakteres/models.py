"""The lexicon's public schemas and classification vocabulary."""

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
    ValidationInfo,
)

LANGUAGES = [
    {"code": "ko", "name": "한국어", "family": "현대 언어"},
    {"code": "en", "name": "영어", "family": "현대 언어"},
    {"code": "ja", "name": "일본어", "family": "현대 언어"},
    {"code": "zh", "name": "중국어", "family": "현대 언어"},
    {"code": "fr", "name": "프랑스어", "family": "현대 언어"},
    {"code": "de", "name": "독일어", "family": "현대 언어"},
    {"code": "es", "name": "스페인어", "family": "현대 언어"},
    {"code": "ar", "name": "아랍어", "family": "현대 언어"},
    {"code": "la", "name": "라틴어", "family": "고전 언어"},
    {"code": "grc", "name": "고전 그리스어", "family": "고전 언어"},
    {"code": "sa", "name": "산스크리트어", "family": "고전 언어"},
]
LANGUAGE_SECTIONS = dict(
    zip(
        ["ko", "en", "ja", "zh", "fr", "de", "es", "ar", "la", "grc", "sa"],
        [
            "Korean",
            "English",
            "Japanese",
            "Chinese",
            "French",
            "German",
            "Spanish",
            "Arabic",
            "Latin",
            "Ancient Greek",
            "Sanskrit",
        ],
    )
)


def canonical_language(value):
    value = value.strip()
    aliases = {l["name"].casefold(): l["code"] for l in LANGUAGES}
    aliases.update({name.casefold(): code for code, name in LANGUAGE_SECTIONS.items()})
    aliases.update({code: code for code in LANGUAGE_SECTIONS})
    aliases.update({"고대 그리스어": "grc", "고전 라틴어": "la", "산스크리트": "sa"})
    return aliases.get(value.casefold(), value)


ELEMENTS = {
    "fire": "불",
    "water": "물",
    "earth": "대지",
    "air": "바람",
    "ice": "얼음",
    "lightning": "번개",
    "light": "빛",
    "shadow": "그림자",
    "nature": "자연",
    "mind": "정신",
    "time": "시간",
    "space": "공간",
}
SCHOOLS = {
    "attack": "공격",
    "defense": "방어",
    "healing": "치유",
    "summoning": "소환",
    "transformation": "변환",
    "control": "제어",
    "utility": "보조",
}
TONES = {
    "lyrical": "서정적인",
    "solemn": "장엄한",
    "concise": "짧고 선명한",
    "ancient": "고풍스러운",
}


def language_name(code):
    return next((l["name"] for l in LANGUAGES if l["code"] == code), code)


class SourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    word: str = Field(max_length=120)
    title: str = Field(max_length=200)
    url: str = Field(
        pattern=r"^https://en\.wiktionary\.org/w/index\.php\?oldid=\d+#",
        max_length=1000,
    )
    language: str = Field(max_length=80)
    excerpt: str = Field(max_length=400)
    ipa: list[str] = Field(default_factory=list, max_length=8)


class LanguageVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal[
        "references_found",
        "not_found",
        "unavailable",
        "demo",
        "stale",
        "author_defined",
    ]
    fingerprint: str = Field(max_length=64)
    checked_at: str = Field(max_length=60)
    provider: str = "Wiktionary"
    searched_words: list[str] = Field(default_factory=list, max_length=4)
    sources: list[SourceEvidence] = Field(default_factory=list, max_length=4)
    note: str = Field(max_length=1000)


class LanguageMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=600)


class LanguageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=2, max_length=300)
    history: list[LanguageMessage] = Field(default_factory=list, max_length=10)


class LanguageChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolved: bool
    language: str = Field(max_length=80)
    reply: str = Field(min_length=1, max_length=600)


class SpellInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    incantation: str = Field(min_length=1, max_length=1200)
    language_kind: Literal["natural", "constructed"] = "natural"
    language: str = Field(min_length=2, max_length=80)
    elements: list[str] = Field(min_length=1, max_length=4)
    school: str = "utility"
    romanization: str = Field(default="", max_length=1200)
    hangul_pronunciation: str = Field(default="", max_length=1200)
    ipa: str = Field(default="", max_length=1200)
    pronunciation_note: str = Field(default="", max_length=600)
    verification: LanguageVerification | None = None
    literal_meaning: str = Field(default="", max_length=1200)
    effect: str = Field(min_length=1, max_length=2000)
    target: str = Field(default="", max_length=200)
    limitations: str = Field(default="", max_length=2000)
    world: str = Field(default="나의 세계관", min_length=1, max_length=100)
    notes: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    language_status: Literal["ai_unverified", "author_edited", "demo_untranslated"] = (
        "author_edited"
    )
    origin: Literal["manual", "ai", "demo"] = "manual"

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value, info: ValidationInfo):
        return (
            value
            if info.data.get("language_kind") == "constructed"
            else canonical_language(value)
        )

    @field_validator("elements")
    @classmethod
    def known_elements(cls, values):
        if any(v not in ELEMENTS for v in values):
            raise ValueError("지원하지 않는 속성입니다.")
        return list(dict.fromkeys(values))

    @field_validator("school")
    @classmethod
    def known_school(cls, value):
        if value not in SCHOOLS:
            raise ValueError("지원하지 않는 주문 계열입니다.")
        return value

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, values):
        if any(len(v) > 50 for v in values):
            raise ValueError("태그는 50자 이하여야 합니다.")
        return list(dict.fromkeys(v.strip() for v in values if v.strip()))

    @model_validator(mode="after")
    def author_language_definition(self):
        if self.language_kind == "constructed":
            if not self.hangul_pronunciation or not self.literal_meaning:
                raise ValueError(
                    "인공 언어는 작가가 발음과 의미를 직접 입력해야 합니다. IPA는 선택 사항입니다."
                )
            self.language_status = "author_edited"
            self.verification = None
        return self


class SaveSpell(SpellInput):
    acknowledge_conflicts: bool = False


class UpdateSpell(SaveSpell):
    version: int = Field(ge=1)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=4, max_length=2000)
    language_kind: Literal["natural", "constructed"] = "natural"
    language: str = Field(default="ko", min_length=2, max_length=80)
    author_incantation: str = Field(default="", max_length=1200)
    author_pronunciation: str = Field(default="", max_length=1200)
    author_meaning: str = Field(default="", max_length=1200)
    author_ipa: str = Field(default="", max_length=1200)
    elements: list[str] = Field(
        default_factory=lambda: ["light"], min_length=1, max_length=4
    )
    school: str = "auto"
    tone: str = "lyrical"
    world: str = Field(default="나의 세계관", min_length=1, max_length=100)
    target: str = Field(default="", max_length=200)
    limitations: str = Field(default="", max_length=1000)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value, info: ValidationInfo):
        return (
            value
            if info.data.get("language_kind") == "constructed"
            else canonical_language(value)
        )

    @field_validator("elements")
    @classmethod
    def known_elements(cls, values):
        return SpellInput.known_elements(values)

    @field_validator("school")
    @classmethod
    def known_school(cls, value):
        if value != "auto" and value not in SCHOOLS:
            raise ValueError("지원하지 않는 주문 계열입니다.")
        return value

    @field_validator("tone")
    @classmethod
    def known_tone(cls, value):
        if value not in TONES:
            raise ValueError("지원하지 않는 문체입니다.")
        return value

    @model_validator(mode="after")
    def require_author_input(self):
        if self.language_kind == "constructed" and not all(
            (self.author_incantation, self.author_pronunciation, self.author_meaning)
        ):
            raise ValueError(
                "인공 언어의 주문문·발음·의미를 입력해 주세요. IPA는 선택 사항입니다."
            )
        return self


class ReviewRequest(SpellInput):
    exclude_id: str | None = Field(default=None, max_length=40)
    use_ai: bool = False
