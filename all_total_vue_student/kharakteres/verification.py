"""Bounded, key-free web dictionary search. Evidence is lexical, never a grammar certificate."""

import asyncio
import hashlib
import json
import os
import logging
import re
import time
import unicodedata
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from langsmith import traceable

from .models import LANGUAGE_SECTIONS as SECTIONS, canonical_language
from .language_catalog import CATALOG

API = "https://en.wiktionary.org/w/api.php"
WIKT_API = "https://api.wiktapi.dev/v1/en/word/"
PROVIDERS = {"wiktionary": "Wiktionary", "wiktapi": "WiktAPI (Kaikki/Wiktextract)"}
logger = logging.getLogger(__name__)
# Supported codes/names resolve through the shared Korean-named catalog. This legacy
# fallback preserves older free-text records; do not add new catalog languages here.
EXTRA_CODES = {"Portuguese": "pt", "Russian": "ru", "Finnish": "fi", "Greek": "el"}


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
_BACKOFF_UNTIL = {}
_DENIED_HOSTS = set()


async def get_dictionary(client, params, url=API, missing_ok=False):
    """Honor provider limits; a denied provider is not retried through other routes."""
    host = httpx.URL(url).host
    if host in _DENIED_HOSTS:
        raise ValueError("dictionary_access_denied")
    if time.monotonic() < _BACKOFF_UNTIL.get(host, 0):
        raise ValueError("dictionary_rate_limited")
    response = await client.get(url, params=params)
    if response.status_code in {429, 503}:
        try:
            delay = max(0, float(response.headers.get("Retry-After", "1")))
        except ValueError:
            delay = 1
        _BACKOFF_UNTIL[host] = time.monotonic() + max(1, delay)
        if delay <= 3:
            await asyncio.sleep(delay)
            response = await client.get(url, params=params)
            if response.status_code in {429, 503}:
                try:
                    delay = max(1, float(response.headers.get("Retry-After", "1")))
                except ValueError:
                    delay = 1
                _BACKOFF_UNTIL[host] = time.monotonic() + delay
    if response.status_code == 403:
        _DENIED_HOSTS.add(host)
        logger.warning("Dictionary provider denied access: host=%s status=403", host)
    if missing_ok and response.status_code == 404:
        return None
    response.raise_for_status()
    return response


def failure_note(errors):
    """Only controlled diagnostics are shown; never echo proxy URLs or credentials."""
    if any(isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 403
           or isinstance(e, ValueError) and str(e) == "dictionary_access_denied" for e in errors):
        return "사전 제공자가 접근을 거절했습니다(HTTP 403). 서버의 접근 정책을 확인해 주세요. "
    if any(isinstance(e, httpx.HTTPStatusError) and e.response.status_code in {429, 503}
           or isinstance(e, ValueError) and str(e) == "dictionary_rate_limited" for e in errors):
        return "사전 제공자의 요청 제한 또는 일시 중단입니다. 잠시 후 다시 확인해 주세요. "
    if any(isinstance(e, (TimeoutError, httpx.TimeoutException)) for e in errors):
        return "웹 사전 응답 시간이 초과되었습니다. "
    if any(isinstance(e, httpx.ConnectError) for e in errors):
        return "웹 사전에 연결하지 못했습니다. 서버의 DNS·네트워크·TLS 설정을 확인해 주세요. "
    if any(isinstance(e, ValueError) and str(e) == "dictionary_language_unsupported" for e in errors):
        return "선택한 사전 제공자에서 이 언어의 코드를 확인하지 못했습니다. "
    return "일부 사전 요청 또는 응답 처리에 실패했습니다. "


async def lookup_wiktapi(client, word, language):
    """Read independently published dump data, not a relay to a denied Wiki endpoint.

Definitions/pronunciations expose lang_code; the raw word route does not currently
include enough language metadata to safely distinguish homographs.
"""
    record = CATALOG.get(language)
    code = record["dictionary_code"] if record else next((v for k,v in EXTRA_CODES.items() if k.casefold()==language.casefold()),None)
    if code is None:
        raise ValueError("dictionary_language_unsupported")
    url = WIKT_API + quote(word, safe="")
    response = await get_dictionary(client, {"lang": code}, url + "/definitions", missing_ok=True)
    if response is None:
        return None
    data = response.json()
    if (not isinstance(data, dict) or data.get("edition") != "en"
        or unicodedata.normalize("NFC", str(data.get("word", ""))).casefold() != unicodedata.normalize("NFC", word).casefold()
        or not isinstance(data.get("definitions"), list)):
        raise ValueError("Dictionary data shape error")
    definitions = [entry for entry in data["definitions"] if isinstance(entry, dict) and entry.get("lang_code") == code]
    if not definitions:
        return None
    glosses = [gloss for entry in definitions for sense in entry.get("senses", [])
               if isinstance(sense, dict) for gloss in sense.get("glosses", []) if isinstance(gloss, str) and gloss.strip()]
    if not glosses:
        return None
    evidence = {
        "word": word, "title": word, "language": (record["dictionary_section"] or record["english_name"]) if record else language,
        "url": str(response.request.url),
        "excerpt": " ".join(glosses[0].split()[:20])[:200], "ipa": [],
    }
    if record and record["dictionary_section"]:
        evidence["origin_url"] = "https://en.wiktionary.org/wiki/" + quote(word,safe="") + "#" + quote(record["dictionary_section"].replace(" ","_"))
    # Pronunciation is optional. Do not lose definitions if this extra request fails.
    try:
        pronunciation = await get_dictionary(client, {"lang": code}, url + "/pronunciations", missing_ok=True)
        if pronunciation is not None:
            data = pronunciation.json()
            if data.get("word") == word and data.get("edition") == "en":
                values = [sound["ipa"] for entry in data.get("pronunciations", [])
                          if isinstance(entry, dict) and entry.get("lang_code") == code
                          for sound in entry.get("sounds", []) if isinstance(sound, dict)
                          and isinstance(sound.get("ipa"), str) and 0 < len(sound["ipa"]) <= 150]
                evidence["ipa"] = list(dict.fromkeys(values))[:8]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        pass
    return evidence


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
    provider = os.getenv("SPELL_DICTIONARY_PROVIDER", "wiktapi").strip().lower()
    result = {
        "status": "not_found",
        "fingerprint": fingerprint(draft),
        "checked_at": datetime.now(UTC).isoformat(),
        "provider": PROVIDERS.get(provider, provider),
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
    if provider not in PROVIDERS:
        return {**result, "status": "unavailable", "note": "사전 제공자 설정 오류입니다. SPELL_DICTIONARY_PROVIDER를 wiktionary 또는 wiktapi로 설정하세요."}
    if provider == "wiktapi":
        result["note"] = "WiktAPI가 배포하는 Kaikki/Wiktextract 사전 데이터를 조회했습니다. 최신 Wiktionary 판본을 직접 확인한 결과가 아닙니다. " + SCOPE
    scope = result["note"]
    record = CATALOG.get(draft["language"])
    language = (record["dictionary_section"] or record["english_name"]) if record else SECTIONS.get(canonical_language(draft["language"]), draft["language"])
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
                    key = (provider, language, word)
                    cached = _CACHE.get(key) if transport is None else None
                    if cached and time.monotonic() - cached[0] < 600:
                        if cached[1]:
                            collected.append(deepcopy(cached[1]))
                        return deepcopy(cached[1])
                    async with semaphore:
                        evidence = await (lookup_wiktapi(client, word, record["code"] if record else language)
                                          if provider == "wiktapi" else lookup(client, word, language))
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
            result["note"] = failure_note([x for x in found if isinstance(x, Exception)]) + scope
    except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        result.update(
            status="references_found" if collected else "unavailable",
            sources=collected,
            note=failure_note([exc]) + scope,
        )
    return result
