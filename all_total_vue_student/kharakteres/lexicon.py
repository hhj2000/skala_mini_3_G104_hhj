"""같은 세계관의 주문 분류·AND 텍스트 검색·설명 가능한 규칙 충돌 검토.

이름/주문문 중복·정의 차이·유사 효과를 검토 후보로 반환한다. 의미적 모순의
확정 판정은 아니며 AI 의미 충돌 검토와 별도의 정답표/지표로 평가한다.
"""

import unicodedata
from difflib import SequenceMatcher

from .models import ELEMENTS, SCHOOLS, language_name


def normalize(text):
    return "".join(
        c
        for c in unicodedata.normalize("NFKC", text).casefold()
        if unicodedata.category(c)[0] in {"L", "N", "M"}
    )


def search(spells, query="", language="", element="", school="", world=""):
    rows = [
        s
        for s in spells
        if (not language or s["language"] == language)
        and (not element or element in s["elements"])
        and (not school or s["school"] == school)
        and (not world or s["world"] == world)
    ]
    tokens = [normalize(t) for t in query.split() if normalize(t)]
    if tokens:
        scored = []
        for s in rows:
            text = normalize(
                " ".join(
                    [
                        s["name"],
                        s["incantation"],
                        s["effect"],
                        s["literal_meaning"],
                        s.get("hangul_pronunciation", ""),
                        s.get("ipa", ""),
                        s.get("romanization", ""),
                        s["notes"],
                        language_name(s["language"]),
                        SCHOOLS[s["school"]],
                        " ".join(ELEMENTS[e] for e in s["elements"]),
                        " ".join(s["tags"]),
                    ]
                )
            )
            if all(t in text for t in tokens):
                scored.append(
                    (sum(3 if t in normalize(s["name"]) else 1 for t in tokens), s)
                )
        rows = [s for _, s in sorted(scored, key=lambda pair: pair[0], reverse=True)]
    return rows


def review(draft, spells, exclude_id=None):
    issues = []
    for s in spells:
        if s["id"] == exclude_id or s["world"] != draft["world"]:
            continue
        shared = {"spell_id": s["id"], "spell_name": s["name"], "source": "rules"}
        same_name = normalize(s["name"]) == normalize(draft["name"])
        same_words = normalize(s["incantation"]) == normalize(draft["incantation"])
        if same_words:
            issues.append(
                {
                    **shared,
                    "severity": "high",
                    "kind": "incantation_collision",
                    "message": "같은 세계관에 동일한 주문문이 있습니다. 변형 주문인지 확인하세요.",
                }
            )
        if same_name:
            issues.append(
                {
                    **shared,
                    "severity": "high",
                    "kind": "name_collision",
                    "message": "같은 세계관에 동일한 주문 이름이 있습니다.",
                }
            )
        if (same_name or same_words) and (
            set(s["elements"]) != set(draft["elements"])
            or s["school"] != draft["school"]
        ):
            issues.append(
                {
                    **shared,
                    "severity": "high",
                    "kind": "definition_mismatch",
                    "message": "이름 또는 주문문은 같지만 속성·계열이 다릅니다. 설정 차이를 확인하세요.",
                }
            )
        similarity = SequenceMatcher(
            None, normalize(s["effect"]), normalize(draft["effect"])
        ).ratio()
        if (
            not same_name
            and not same_words
            and similarity >= 0.72
            and len(normalize(draft["effect"])) >= 8
        ):
            issues.append(
                {
                    **shared,
                    "severity": "medium",
                    "kind": "similar_effect",
                    "message": "효과 설명이 유사합니다. 중복 효과 또는 의도한 파생 주문인지 검토하세요.",
                }
            )
    return {
        "issues": issues,
        "has_high": any(i["severity"] == "high" for i in issues),
        "scope": "같은 세계관의 저장된 주문만 비교",
        "note": "중복·유사성은 오류 확정이 아닙니다. 의도한 변형은 검토 후 저장할 수 있습니다.",
    }


def stats(spells):
    return {
        "total": len(spells),
        "languages": len({s["language"] for s in spells}),
        "elements": len({e for s in spells for e in s["elements"]}),
        "worlds": len({s["world"] for s in spells}),
    }
