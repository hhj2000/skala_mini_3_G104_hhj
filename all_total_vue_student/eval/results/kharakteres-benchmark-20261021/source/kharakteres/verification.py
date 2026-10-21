"""Bounded, key-free web dictionary search. Evidence is lexical, never a grammar certificate."""

import asyncio
import hashlib
import json
import re
import time
import unicodedata
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from langsmith import traceable

from .models import LANGUAGE_SECTIONS as SECTIONS

API = "https://en.wiktionary.org/w/api.php"

INPUT_KEYS = (
    "language_kind",
    "language",
    "incantation",
    "romanization",
    "hangul_pronunciation",
    "ipa",
    "pronunciation_note",
)
SCOPE = "주문 앞부분의 최대 4개 단어를 웹 사전에서 검색했습니다. 같은 표제어의 해당 언어 항목만 출처로 표시합니다. 문장 전체의 문법·뜻·한글 전사·IPA 일치 여부는 미검증입니다. 굴절형·띄어쓰기 없는 언어·창작어는 검색되지 않을 수 있습니다."


def fingerprint(draft):
    text = json.dumps(
        {k: draft.get(k, "") for k in INPUT_KEYS}, ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(text.encode()).hexdigest()


def invalidate_changed_evidence(payload):
    evidence = payload.get("verification")
    if evidence and evidence["fingerprint"] != fingerprint(payload):
        payload["verification"] = {
            **evidence,
            "status": "stale",
            "sources": [],
            "note": "언어·주문문·발음이 수정되어 이전 출처 검토가 만료되었습니다. 웹 출처를 다시 확인해 주세요.",
        }
    return payload


def words(text):
    tokens, current = [], ""
    for c in unicodedata.normalize("NFC", text):
        if unicodedata.category(c)[0] in {"L", "M"}:
            current += c
        elif current:
            tokens.append(current)
            current = ""
    if current:
        tokens.append(current)
    return list(dict.fromkeys(t.lower() for t in tokens if len(t) <= 120))[:4]


def section_text(raw, language):
    # A homograph's English section must never count as Latin/Greek/etc. evidence.
    for name, content in re.findall(
        r"^==([^=\n]+)==\s*\n(.*?)(?=^==[^=\n]+==\s*$|\Z)",
        raw,
        re.MULTILINE | re.DOTALL,
    ):
        if name.strip().casefold() == language.casefold():
            return content
    return ""


def excerpt_from(raw):
    definitions = re.findall(r"^# ([^\n]+)", raw, re.MULTILINE)
    if not definitions:
        return "해당 언어의 표제어 항목 확인. 상세 의미와 발음은 원문 참조."
    text = definitions[0]
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"<[^>]*>|'{2,}", "", text)
    return " ".join(text.split()[:20])[:200] or "상세 의미는 원문 참조."


_CACHE = OrderedDict()
_BACKOFF_UNTIL = 0.0


async def get_dictionary(client, params):
    global _BACKOFF_UNTIL
    if time.monotonic() < _BACKOFF_UNTIL:
        raise ValueError("Dictionary rate limit cooldown")
    response = await client.get(API, params=params)
    if response.status_code in {429, 503}:
        try:
            delay = max(0, float(response.headers.get("Retry-After", "1")))
        except ValueError:
            delay = 1
        if response.status_code == 429:
            _BACKOFF_UNTIL = time.monotonic() + max(1, delay)
        if delay <= 3:
            await asyncio.sleep(delay)
            response = await client.get(API, params=params)
            if response.status_code == 429:
                try:
                    next_delay = float(response.headers.get("Retry-After", "1"))
                except ValueError:
                    next_delay = 1
                _BACKOFF_UNTIL = time.monotonic() + max(1, next_delay)
    response.raise_for_status()
    return response


async def lookup(client, word, language):
    response = await get_dictionary(
        client,
        params={
            "action": "query",
            "format": "json",
            "list": "search",
            "srnamespace": 0,
            "srsearch": f'intitle:"{word}"',
            "srlimit": 3,
        },
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise ValueError("Dictionary search error")
    match = next(
        (
            p
            for p in data.get("query", {}).get("search", [])
            if unicodedata.normalize("NFC", p["title"]).casefold()
            == unicodedata.normalize("NFC", word).casefold()
        ),
        None,
    )
    if not match:
        return None
    response = await get_dictionary(
        client,
        params={
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "pageids": match["pageid"],
            "prop": "revisions",
            "rvslots": "main",
            "rvprop": "ids|content",
            "rvlimit": 1,
        },
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise ValueError("Dictionary content error")
    pages = data.get("query", {}).get("pages", [])
    if not pages or not pages[0].get("revisions"):
        return None
    revision = pages[0]["revisions"][0]
    raw = section_text(revision["slots"]["main"]["content"], language)
    if not raw:
        return None
    # Only literal IPA in the retrieved section is quoted; auto-generated template
    # pronunciations are not guessed or silently borrowed from a different language.
    ipa = []
    for params in re.findall(r"\{\{IPA\|([^{}]+)\}\}", raw):
        ipa += [
            v
            for v in params.split("|")[1:]
            if v.startswith(("/", "[")) and len(v) <= 150
        ]
    return {
        "word": word,
        "title": match["title"][:200],
        "language": language,
        "url": f"https://en.wiktionary.org/w/index.php?oldid={int(revision['revid'])}#{quote(language.replace(' ', '_'))}",
        "excerpt": excerpt_from(raw),
        "ipa": list(dict.fromkeys(ipa))[:8],
    }


@traceable(name="language.web_dictionary_search")
async def verify_language(draft, demo=False, transport=None):
    result = {
        "status": "not_found",
        "fingerprint": fingerprint(draft),
        "checked_at": datetime.now(UTC).isoformat(),
        "provider": "Wiktionary",
        "searched_words": words(draft["incantation"]),
        "sources": [],
        "note": SCOPE,
    }
    if draft.get("language_kind") == "constructed":
        return {
            **result,
            "status": "author_defined",
            "provider": "author",
            "searched_words": [],
            "note": "작가가 직접 정의한 언어입니다. 발음·의미는 작가 입력을 사용하며 웹 사전이나 LLM으로 인증하지 않습니다.",
        }
    if demo:
        return {
            **result,
            "status": "demo",
            "note": "fake 데모는 웹 검색을 수행하지 않습니다. 실제 모드에서 출처를 확인하세요.",
        }
    language = SECTIONS.get(draft["language"], draft["language"])
    collected = []
    try:
        async with asyncio.timeout(25):
            async with httpx.AsyncClient(
                timeout=10,
                transport=transport,
                headers={
                    "User-Agent": "Kharakteres/1.0 (educational dictionary source lookup)",
                },
            ) as client:
                semaphore = asyncio.Semaphore(2)

                async def cached_lookup(word):
                    key = (language, word)
                    cached = _CACHE.get(key) if transport is None else None
                    if cached and time.monotonic() - cached[0] < 600:
                        if cached[1]:
                            collected.append(deepcopy(cached[1]))
                        return deepcopy(cached[1])
                    async with semaphore:
                        evidence = await lookup(client, word, language)
                    if transport is None:
                        _CACHE[key] = (time.monotonic(), deepcopy(evidence))
                        _CACHE.move_to_end(key)
                        while len(_CACHE) > 256:
                            _CACHE.popitem(last=False)
                    if evidence:
                        collected.append(evidence)
                    return evidence

                found = await asyncio.gather(
                    *(cached_lookup(word) for word in result["searched_words"]),
                    return_exceptions=True,
                )
        result["sources"] = [x for x in found if isinstance(x, dict)]
        errors = any(isinstance(x, Exception) for x in found)
        result["status"] = (
            "references_found"
            if result["sources"]
            else "unavailable"
            if errors
            else "not_found"
        )
        if errors:
            remaining = max(0, int(_BACKOFF_UNTIL - time.monotonic()) + 1)
            result["note"] = (
                f"웹 사전 요청 제한입니다. 약 {remaining}초 뒤 다시 확인해 주세요. "
                if remaining
                else "일부 웹 검색 요청에 실패했습니다. "
            ) + SCOPE
    except (TimeoutError, httpx.HTTPError, ValueError, KeyError):
        result.update(
            status="references_found" if collected else "unavailable",
            sources=collected,
            note="일부 웹 조회를 시간 내 완료하지 못했습니다. " + SCOPE,
        )
    return result
