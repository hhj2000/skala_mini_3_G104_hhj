"""Provider isolation, provenance validation and explicit external denial handling."""
import asyncio
import httpx
import pytest
from pydantic import ValidationError
from kharakteres import verification as web
from kharakteres.models import LanguageVerification, SourceEvidence
from test_language_sources import draft as original_draft
from auth_support import authenticated_client
from kharakteres.api import app


def draft(**changes):
    return {**original_draft(), "incantation":"lux", **changes}


@pytest.fixture(autouse=True)
def isolated_providers(monkeypatch):
    monkeypatch.setenv('SPELL_DICTIONARY_PROVIDER','wiktapi')
    monkeypatch.setattr(web,'_BACKOFF_UNTIL',{})
    monkeypatch.setattr(web,'_DENIED_HOSTS',set())
    monkeypatch.setattr(web,'_CACHE',web.OrderedDict())


def payload(kind, entries, word='lux'):
    return {'word':word,'edition':'en',kind:entries}


def test_wiktapi_requires_language_code_and_keeps_real_data_links():
    def handle(request):
        assert request.url.host=='api.wiktapi.dev'
        assert request.url.params['lang']=='la'
        if request.url.path.endswith('/definitions'):
            return httpx.Response(200,json=payload('definitions',[
                {'lang_code':'en','senses':[{'glosses':['WRONG LANGUAGE']}]},
                {'lang_code':'la','senses':[{'glosses':['light (of the sun)']}]},
            ]))
        return httpx.Response(200,json=payload('pronunciations',[
            {'lang_code':'en','sounds':[{'ipa':'wrong'}]},
            {'lang_code':'la','sounds':[{'ipa':'/luːks/'}]},
        ]))
    result=asyncio.run(web.verify_language(draft(),transport=httpx.MockTransport(handle)))
    assert result['status']=='references_found'
    assert result['provider'].startswith('WiktAPI')
    source=result['sources'][0]
    assert source['excerpt']=='light (of the sun)' and source['ipa']==['/luːks/']
    assert source['url']=='https://api.wiktapi.dev/v1/en/word/lux/definitions?lang=la'
    assert source['origin_url']=='https://en.wiktionary.org/wiki/lux#Latin'
    assert '직접 확인한 결과가 아닙니다' in result['note']
    LanguageVerification.model_validate(result)


@pytest.mark.parametrize('body',[
    payload('definitions',[{'lang_code':'en','senses':[{'glosses':['wrong']}]}]),
    payload('definitions',[]),
])
def test_wiktapi_does_not_use_english_homograph(body):
    result=asyncio.run(web.verify_language(draft(),transport=httpx.MockTransport(lambda _:httpx.Response(200,json=body))))
    assert result['status']=='not_found' and not result['sources']


def test_wiktapi_404_is_not_a_network_failure():
    result=asyncio.run(web.verify_language(draft(),transport=httpx.MockTransport(lambda _:httpx.Response(404))))
    assert result['status']=='not_found'


def test_definitions_survive_optional_pronunciation_timeout():
    def handle(request):
        if request.url.path.endswith('/pronunciations'): raise httpx.ReadTimeout('timeout',request=request)
        return httpx.Response(200,json=payload('definitions',[{'lang_code':'la','senses':[{'glosses':['light']}]}]))
    result=asyncio.run(web.verify_language(draft(),transport=httpx.MockTransport(handle)))
    assert result['status']=='references_found' and result['sources'][0]['ipa']==[]


def test_denied_provider_is_not_retried_or_switched(monkeypatch):
    monkeypatch.setenv('SPELL_DICTIONARY_PROVIDER','wiktionary')
    requests=[]
    def handle(request):
        requests.append(request)
        return httpx.Response(403,text='private diagnostic or proxy credentials')
    async def run():
        transport=httpx.MockTransport(handle)
        first=await web.verify_language(draft(),transport=transport)
        second=await web.verify_language(draft(),transport=transport)
        return first,second
    for result in asyncio.run(run()):
        assert result['status']=='unavailable' and '403' in result['note']
        assert 'private diagnostic' not in result['note']
    assert len(requests)==1
    assert all(r.url.host=='en.wiktionary.org' for r in requests)
    assert 'api.wiktapi.dev' not in web._DENIED_HOSTS


def test_long_retry_after_is_respected_without_retry():
    calls=[]
    def handle(request):
        calls.append(request)
        return httpx.Response(429,headers={'Retry-After':'60'})
    result=asyncio.run(web.verify_language(draft(),transport=httpx.MockTransport(handle)))
    assert result['status']=='unavailable' and '요청 제한' in result['note']
    assert len(calls)==1


def test_invalid_json_and_unknown_provider_are_explicit(monkeypatch):
    result=asyncio.run(web.verify_language(draft(),transport=httpx.MockTransport(lambda _:httpx.Response(200,text='<html>not a dictionary</html>'))))
    assert result['status']=='unavailable'
    monkeypatch.setenv('SPELL_DICTIONARY_PROVIDER','wrong')
    result=asyncio.run(web.verify_language(draft()))
    assert result['status']=='unavailable' and '설정 오류' in result['note']


def test_provider_cache_keys_are_separate(monkeypatch):
    monkeypatch.setattr(web,'_CACHE',web.OrderedDict({('wiktionary','Latin','lux'):(float('inf'),{'word':'wrong'})}))
    calls=[]
    def handle(request):
        calls.append(request)
        if request.url.path.endswith('/definitions'):
            return httpx.Response(200,json=payload('definitions',[{'lang_code':'la','senses':[{'glosses':['light']}]}]))
        return httpx.Response(200,json=payload('pronunciations',[]))
    original=httpx.AsyncClient
    def client(**kwargs):
        kwargs['transport']=httpx.MockTransport(handle)
        return original(**kwargs)
    monkeypatch.setattr(web.httpx,'AsyncClient',client)
    result=asyncio.run(web.verify_language({**draft(),'incantation':'lux'}))
    assert result['sources'][0]['excerpt']=='light' and len(calls)==2
    assert ('wiktapi','Latin','lux') in web._CACHE


def test_new_evidence_survives_api_save_read_and_legacy_data(tmp_path,monkeypatch):
    monkeypatch.setenv('SPELL_DB_PATH',str(tmp_path/'spells.sqlite'))
    evidence={'word':'lux','title':'lux','language':'Latin','excerpt':'light','ipa':[],
              'url':'https://api.wiktapi.dev/v1/en/word/lux/definitions?lang=la',
              'origin_url':'https://en.wiktionary.org/wiki/lux#Latin'}
    body=draft()
    body['verification']={'status':'references_found','fingerprint':web.fingerprint(body),
                          'checked_at':'2026-10-21T00:00:00+00:00','provider':'WiktAPI (Kaikki/Wiktextract)',
                          'searched_words':['lux'],'sources':[evidence],'note':'dump data'}
    with authenticated_client(app) as client:
        response=client.post('/api/spells',json=body)
        assert response.status_code==201,response.text
        saved=response.json()['spell']
        assert client.get('/api/spells/'+saved['id']).json()['verification']['sources'][0]['origin_url']==evidence['origin_url']
    legacy={**evidence,'url':'https://en.wiktionary.org/w/index.php?oldid=123#Latin'}
    legacy.pop('origin_url')
    assert SourceEvidence.model_validate(legacy).origin_url is None
    for url in ['javascript:alert(1)','https://api.wiktapi.dev.evil/v1/en/word/lux/definitions?lang=la']:
        with pytest.raises(ValidationError): SourceEvidence.model_validate({**evidence,'url':url})
