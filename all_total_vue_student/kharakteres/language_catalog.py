"""Shared natural-language catalog for UI, LLM context, persistence and dictionaries.

Bundled ISO metadata works without network; provider listings are availability hints
across editions, never proof of an English-edition entry or LLM language competence.
Constructed/special ISO types and unmapped provider codes do not become natural
languages just because a remote API returned them. Only bundled Korean-named languages
are selectable; refresh changes dictionary availability, never this stable scope.
Names sort in Korean alphabetical order; ISO ancient/historical types share the
classical UI group while their canonical ISO type is preserved.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import threading
import math
from email.utils import parsedate_to_datetime
from tempfile import NamedTemporaryFile
from functools import wraps
import time
import unicodedata

import httpx
from .language_defaults import LANGUAGES, LANGUAGE_SECTIONS, LANGUAGE_ALIASES, canonical_basic

DATA = Path(__file__).with_name('data')
PROVIDER_URL = 'https://api.wiktapi.dev/v1/languages'
ROOT = Path(__file__).resolve().parents[1]
TYPES = {'L':'현대 언어', 'A':'고전 언어', 'H':'고전 언어', 'E':'사멸 언어'}
logger = logging.getLogger(__name__)


def folded(value):
    return unicodedata.normalize('NFKC',value).strip().casefold()


def cache_path():
    path=Path(os.getenv('SPELL_LANGUAGE_CATALOG_CACHE',str(ROOT/'data/language_catalog.json'))).expanduser()
    return path if path.is_absolute() else ROOT/path


def synchronized(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        with self.lock:
            return method(self,*args,**kwargs)
    return call


def retry_delay(value):
    try:
        delay=float(value)
    except (ValueError,TypeError):
        try:
            date=parsedate_to_datetime(value)
            delay=date.timestamp()-time.time()
        except (ValueError,TypeError,OverflowError):
            delay=60
    return max(60,delay) if math.isfinite(delay) else 86400


class LanguageCatalog:
    def __init__(self, iso_path=DATA/'iso639-3.json', snapshot_path=DATA/'language-provider-snapshot.json', cache=None):
        self.korean_names=json.loads((DATA/'korean-language-names.json').read_text())
        self.iso_rows=json.loads(Path(iso_path).read_text())['639-3']
        self.iso_by_alias={}
        for row in self.iso_rows:
            for key in ('alpha_2','alpha_3','bibliographic'):
                if row.get(key): self.iso_by_alias[row[key]]=row
        self.cache=Path(cache) if cache is not None else None
        self.lock=threading.RLock()
        self.refresh_lock=asyncio.Lock()
        self.last_attempt=None
        self.next_attempt=0
        self.denied=False
        self.last_refresh_error=None
        payload=json.loads(Path(snapshot_path).read_text())
        mode='bundled'
        self.checked_at=json.loads((DATA/'language-data-sources.json').read_text())['retrieved_at']
        if self.cache and self.cache.exists():
            try:
                cached=json.loads(self.cache.read_text())
                self.validate_payload(cached['data'])
                self.checked_at=cached['checked_at'];payload=cached['data'];mode='disk_cache'
            except (OSError,ValueError,KeyError,TypeError):
                logger.warning('Ignoring invalid language catalog cache')
        self.rebuild(payload,mode)

    def validate_payload(self,payload):
        if not isinstance(payload,dict) or not isinstance(payload.get('languages'),list) or not 1<=len(payload['languages'])<=20000:
            raise ValueError('Invalid language catalog response')
        good=[]
        for row in payload['languages']:
            if not isinstance(row,dict): continue
            code=row.get('lang_code'); name=row.get('lang'); count=row.get('entry_count',0)
            if (not isinstance(code,str) or not re.fullmatch('[a-z]{2,3}',code)
                or not isinstance(name,str) or not 1<=len(name)<=160
                or any(unicodedata.category(c)=='Cc' for c in name)
                or type(count) is not int or count<0): continue
            iso=self.iso_by_alias.get(code)
            if iso and iso.get('type') in TYPES:
                good.append((row,iso))
        if not good: raise ValueError('No recognized natural languages in provider response')
        return good

    def rebuild(self,payload,mode):
        providers={}
        for row,iso in self.validate_payload(payload):
            providers.setdefault(iso['alpha_3'],[]).append(row)
        defaults={row['code']:row for row in LANGUAGES}
        records={}
        for iso in self.iso_rows:
            if iso.get('type') not in TYPES or re.search(r'\b(sign|signed)\b',iso['name'],re.I): continue
            code=iso.get('alpha_2') or iso['alpha_3']
            if code not in self.korean_names: continue
            candidates=providers.get(iso['alpha_3'],[])
            provider=next((r for r in candidates if r['lang_code']==code),None)
            provider=provider or (max(candidates,key=lambda r:r['entry_count']) if candidates else None)
            english=LANGUAGE_SECTIONS.get(code,iso['name'])
            if len(english)>80: continue
            default=defaults.get(code)
            # Korean display names are bundled, so remote refresh cannot expand or rename the list.
            name=self.korean_names[code]
            aliases=[code,iso['alpha_3'],english,iso['name']]
            if iso.get('bibliographic'): aliases.append(iso['bibliographic'])
            # ISO inverted reference names: English, Old (...) -> Old English.
            clean=re.sub(r'\s*\([^)]*\)','',iso['name']).strip()
            if clean and clean!=iso['name']: aliases.append(clean)
            if ',' in clean:
                noun,qualifier=clean.split(',',1)
                aliases.append(qualifier.strip()+' '+noun.strip())
            elif '(' in iso['name']:
                match=re.fullmatch(r'(.+?)\s*\((Ancient|Old|Middle|Modern|Classical)\)',iso['name'])
                if match: aliases.append(match[2]+' '+match[1].strip())
            if provider: aliases.append(provider['lang'])
            aliases.extend(r['lang_code'] for r in candidates)
            aliases.extend(k for k,v in LANGUAGE_ALIASES.items() if v==code)
            if code in LANGUAGE_SECTIONS: aliases.append(LANGUAGE_SECTIONS[code])
            records[code]={'code':code,'name':name,'english_name':english,
                'family':TYPES[iso['type']],
                'type':iso['type'],'scope':iso['scope'],'tier':'default' if default else 'extended',
                'dictionary_listed':bool(provider),'dictionary_code':provider['lang_code'] if provider else code,
                'dictionary_section':LANGUAGE_SECTIONS.get(code),
                'aliases':list(dict.fromkeys(aliases)),
                'quality':'모델별 품질 차이 · 언어 정확도 미검증'}
        # Preserve explicitly curated historical names over generic ISO labels.
        index={}
        for code,row in records.items():
            for alias in [row['name'],*row['aliases']]:
                index.setdefault(folded(alias),set()).add(code)
        ordered=sorted(records.values(),key=lambda r:(unicodedata.normalize('NFC',r['name']),r['code']))
        with self.lock:
            self.records=records;self.index=index;self.ordered=ordered;self.mode=mode

    @synchronized
    def resolve(self,value):
        basic=canonical_basic(value)
        if basic in self.records: return basic
        matches=self.index.get(folded(basic),set())
        return next(iter(matches)) if len(matches)==1 else value.strip()

    @synchronized
    def get(self,value):
        row=self.records.get(self.resolve(value))
        return deepcopy(row) if row else None

    @synchronized
    def metadata(self):
        return {'total':len(self.records),'default_count':len(LANGUAGES),
                'dictionary_listed_count':sum(r['dictionary_listed'] for r in self.ordered),
                'source':self.mode,'checked_at':self.checked_at,'last_refresh_error':self.last_refresh_error,
                'retry_after_seconds':max(0,int(self.next_attempt-time.monotonic()+1)),
                'note':'언어 선택 항목 수이며 LLM 번역 지원 보장 수가 아닙니다. 사전 목록은 여러 판을 합친 정보입니다.'}

    @synchronized
    def search(self,query='',family='',tier='',dictionary_only=False,offset=0,limit=48):
        tokens=folded(query).split()
        exact=self.resolve(query) if query.strip() else None
        rows=[r for r in self.ordered if (not family or (r['type'] in {'A','H'} if family=='C' else r['type']==family))
              and (not tier or r['tier']==tier) and (not dictionary_only or r['dictionary_listed'])
              and (not tokens or r['code']==exact or all(t in folded(' '.join([r['name'],*r['aliases']])) for t in tokens))]
        return {'items':deepcopy(rows[offset:offset+limit]),'total':len(rows),'offset':offset,'limit':limit,'catalog':self.metadata()}

    @synchronized
    def suggestions(self,message,limit=12):
        text=folded(message)
        exact=self.get(message)
        if exact: return [exact]
        candidates=[]
        short_tokens=set(re.findall(r'\w+',text))
        for row in self.ordered:
            if any((len(alias)>3 and folded(alias) in text) or (len(alias)<=3 and folded(alias) in short_tokens) for alias in [row['name'],*row['aliases']]):
                candidates.append(row)
        return deepcopy(candidates[:limit])

    async def refresh(self,transport=None):
        # One provider attempt per minute across users; no blocking startup/network call.
        async with self.refresh_lock:
            if self.denied:
                self.last_refresh_error='provider_access_denied';return self.metadata()
            if time.monotonic()<self.next_attempt:
                return self.metadata()
            self.last_attempt=time.monotonic()
            self.next_attempt=self.last_attempt+60
            try:
                async with httpx.AsyncClient(timeout=8,transport=transport,follow_redirects=False,
                    headers={'User-Agent':'Kharakteres/1.0 (language catalog)'}) as client:
                    async with client.stream('GET',PROVIDER_URL) as response:
                        if response.status_code==403: self.denied=True
                        if response.status_code in (429,503): self.next_attempt=time.monotonic()+retry_delay(response.headers.get("Retry-After"))
                        response.raise_for_status()
                        chunks=[];size=0
                        async for chunk in response.aiter_bytes():
                            size+=len(chunk)
                            if size>4_000_000: raise ValueError('Language catalog too large')
                            chunks.append(chunk)
                payload=json.loads(b''.join(chunks));self.validate_payload(payload)
                self.rebuild(payload,'live')
                self.checked_at=datetime.now(timezone.utc).isoformat();self.last_refresh_error=None
                if self.cache:
                    try:
                        self.cache.parent.mkdir(parents=True,exist_ok=True)
                        with NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.cache.parent,prefix='.language-catalog-',suffix='.tmp',delete=False) as out:
                            temp=Path(out.name)
                            json.dump({'checked_at':self.checked_at,'data':payload},out,ensure_ascii=False)
                        try: temp.replace(self.cache)
                        finally: temp.unlink(missing_ok=True)
                    except OSError:
                        # Read-only deployments can still use the in-process refreshed catalog.
                        logger.warning('Language catalog refresh succeeded but disk cache is unavailable')
            except (httpx.HTTPError,ValueError,KeyError,TypeError):
                self.last_refresh_error='provider_access_denied' if self.denied else 'refresh_unavailable'
            return self.metadata()


CATALOG=LanguageCatalog(cache=cache_path())


def canonical_language(value):
    return CATALOG.resolve(value)


def language_name(value):
    row=CATALOG.get(value)
    return row['name'] if row else value
