"""Natural-language catalog provenance, safe refresh, normalization and API integration."""
import asyncio
import json
import httpx
import pytest
from kharakteres.language_catalog import CATALOG, LanguageCatalog
from kharakteres.models import GenerateRequest, SpellInput, canonical_language
from kharakteres.generation import SpellGenerator
from kharakteres.api import app
from kharakteres import verification
from auth_support import authenticated_client


def data(code='pt',name='포르투갈어'):
    return {'languages':[{'lang_code':code,'lang':name,'entry_count':12}]}


def test_bundled_catalog_only_keeps_korean_named_natural_languages():
    assert CATALOG.metadata()['total']==229
    assert CATALOG.metadata()['default_count']==13
    for name,code in [('Portuguese','pt'),('포르투갈어','pt'),('Finnish','fi'),('히브리어','he'),('fra','fr'),('Old English','ang')]:
        assert canonical_language(name)==code
        assert GenerateRequest(language=name,prompt='작은 등불을 부르는 주문').language==code
    for excluded in ['eo','tlh','qya','mul','und','zxx','unknown','ase','ils']:
        assert CATALOG.get(excluded) is None
    assert len(CATALOG.records)==len(set(CATALOG.records))
    assert all(any('가'<=c<='힣' for c in r['name']) for r in CATALOG.ordered)
    assert [r['name'] for r in CATALOG.ordered]==sorted(r['name'] for r in CATALOG.ordered)
    for code in ['vi','sl','cu']: assert CATALOG.get(code) is not None
    for code in ['non','egy','rmf']: assert CATALOG.get(code) is None
    assert CATALOG.get('he')['tier']=='extended'


def test_search_filters_and_pagination_do_not_repeat_or_hide_matches():
    page=CATALOG.search(query='Hebrew',limit=5)
    assert page['items'][0]['code']=='he'
    first=CATALOG.search(offset=0,limit=20)['items'];second=CATALOG.search(offset=20,limit=20)['items']
    assert not {r['code'] for r in first}&{r['code'] for r in second}
    assert all(r['type']=='H' for r in CATALOG.search(family='H')['items'])
    classical=CATALOG.search(family='C',limit=200)['items']
    expected=[r for r in CATALOG.ordered if r['type'] in {'A','H'}]
    assert classical==expected and classical
    # Current Korean subset has H entries only; exercise the ISO A branch separately.
    fixture_catalog=LanguageCatalog()
    fixture_catalog.records['grc']['type']='A'
    both=fixture_catalog.search(family='C',limit=200)['items']
    assert {r['type'] for r in both}=={'A','H'}
    assert all(r['family']=='고전 언어' for r in classical)
    assert CATALOG.get('cu')['family']==CATALOG.get('ang')['family']=='고전 언어'
    assert all(r['dictionary_listed'] for r in CATALOG.search(dictionary_only=True)['items'])
    assert CATALOG.search('nothislanguagexx')['items']==[]
    finnish=CATALOG.search('Finnish')['items']
    assert [r['name'] for r in finnish]==sorted(r['name'] for r in finnish)
    assert finnish[0]['code']=='fkv' # 가나다순 applies even when fi matches exactly


def test_refresh_is_cached_on_disk_and_reused_without_network(tmp_path):
    cache=tmp_path/'language_catalog.json'
    catalog=LanguageCatalog(cache=cache)
    result=asyncio.run(catalog.refresh(httpx.MockTransport(lambda _:httpx.Response(200,json=data()))))
    assert result['source']=='live' and result['dictionary_listed_count']==1
    assert catalog.get('Portuguese')['dictionary_code']=='pt'
    assert catalog.metadata()['total']==229
    assert catalog.get('sl')['name']=='슬로베니아어'
    assert catalog.get('sl')['dictionary_listed'] is False
    reloaded=LanguageCatalog(cache=cache)
    assert reloaded.metadata()['source']=='disk_cache'
    assert reloaded.get('Portuguese')['dictionary_listed']
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('response',[httpx.Response(500),httpx.Response(200,json=data('tlh','Klingon')),httpx.Response(200,text='broken json')])
def test_failed_or_constructed_only_refresh_preserves_catalog(response):
    catalog=LanguageCatalog();before=catalog.metadata()['dictionary_listed_count']
    after=asyncio.run(catalog.refresh(httpx.MockTransport(lambda _:response)))
    assert after['source']=='bundled' and after['dictionary_listed_count']==before
    assert after['last_refresh_error']=='refresh_unavailable'


def test_denial_and_long_retry_after_stop_additional_calls():
    for status,headers in [(403,{}),(429,{'Retry-After':'3600'})]:
        catalog=LanguageCatalog();calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(status,headers=headers)
        async def run():
            transport=httpx.MockTransport(handler)
            await catalog.refresh(transport);await catalog.refresh(transport)
        asyncio.run(run())
        assert len(calls)==1 and catalog.metadata()['total']==229
        if status==429: assert catalog.metadata()['retry_after_seconds']>3500
        else: assert catalog.denied


def test_invalid_disk_cache_and_read_only_cache_keep_bundled_fallback(tmp_path):
    cache=tmp_path/'cache.json';cache.write_text('bad')
    assert LanguageCatalog(cache=cache).metadata()['source']=='bundled'
    catalog=LanguageCatalog(cache=tmp_path) # a directory cannot become a cache file
    result=asyncio.run(catalog.refresh(httpx.MockTransport(lambda _:httpx.Response(200,json=data()))))
    assert result['source']=='live'


def test_iso_alias_duplicates_are_merged_and_unknown_remote_codes_ignored():
    catalog=LanguageCatalog()
    payload={'languages':[
        {'lang_code':'pt','lang':'Portuguese','entry_count':2},
        {'lang_code':'por','lang':'Português','entry_count':3},
        {'lang_code':'unknown','lang':'invented','entry_count':999},
        {'lang_code':'tlh','lang':'Klingon','entry_count':999},
        {'lang_code':'non','lang':'새로 추가한 한국어 이름','entry_count':999}]}
    catalog.rebuild(payload,'test')
    assert catalog.metadata()['dictionary_listed_count']==1
    assert catalog.get('por')['code']=='pt' and catalog.get('pt')['dictionary_code']=='pt'
    assert catalog.get('unknown') is None
    assert catalog.get('non') is None # remote refresh never expands the bundled Korean list


def test_extended_language_api_selection_save_and_display(tmp_path,monkeypatch):
    monkeypatch.setenv('SPELL_DB_PATH',str(tmp_path/'spells.sqlite'))
    with authenticated_client(app) as client:
        catalog=client.get('/api/catalog').json()
        assert catalog['registered_language_count']==len(catalog['languages'])==catalog['language_catalog']['total']==229
        assert catalog['language_labels']['he']=='히브리어'
        found=client.get('/api/languages',params={'q':'Hebrew','limit':2}).json()
        assert len(found['items'])==1 and found['items'][0]['code']=='he'
        choice=client.post('/api/language',json={'message':'Finnish'}).json()
        assert choice['resolved'] and choice['language']=='fi'
        record=SpellInput(name='빛',incantation='valo',language='Finnish',elements=['light'],effect='밝힌다').model_dump()
        saved=client.post('/api/spells',json=record).json()['spell']
        assert saved['language']=='fi'
        assert client.get('/api/spells/'+saved['id']).json()['language']=='fi'
        classical=client.get('/api/languages',params={'family':'C'}).json()['items']
        assert classical and all(r['type'] in {'A','H'} for r in classical)
        assert all(r['family']=='고전 언어' for r in classical)
        assert client.get('/api/languages',params={'limit':201}).status_code==422
        assert client.get('/api/languages',params={'offset':-1}).status_code==422


def test_llm_interpretation_uses_bounded_candidates_not_whole_catalog():
    class Store:
        def all(self):return []
    class Model:
        name='test'
        def _chat(self,system,user,**kwargs):
            self.system=system;self.user=json.loads(user)
            return json.dumps({'resolved':True,'language':'Finnish','reply':'핀란드어로 준비했습니다.'}),{}
    model=Model();generator=SpellGenerator('openai',model,Store())
    result=asyncio.run(generator.resolve_language('핀란드어로 주문을 만들어 주세요'))
    assert result.language=='fi'
    assert any(r['code']=='fi' for r in model.user['language_candidates'])
    assert len(model.user['language_candidates'])<=25 and len(model.system)<10000
    assert len(json.dumps(model.user))<20000


def test_extended_word_evidence_uses_matched_code_without_guessing_wiki_section(monkeypatch):
    monkeypatch.setenv('SPELL_DICTIONARY_PROVIDER','wiktapi')
    monkeypatch.setattr(verification,'_DENIED_HOSTS',set());monkeypatch.setattr(verification,'_BACKOFF_UNTIL',{})
    def handler(request):
        assert request.url.params['lang']=='fi'
        if request.url.path.endswith('/definitions'):
            return httpx.Response(200,json={'word':'valo','edition':'en','definitions':[{'lang_code':'fi','senses':[{'glosses':['light']}]}]})
        return httpx.Response(200,json={'word':'valo','edition':'en','pronunciations':[]})
    result=asyncio.run(verification.verify_language({'language':'Finnish','incantation':'valo'},transport=httpx.MockTransport(handler)))
    assert result['status']=='references_found' and result['sources'][0]['language']=='Finnish'
    assert not result['sources'][0].get('origin_url') # no invented English-Wiki language fragment
