"""Language names/codes must reach the same catalog, model and dictionary identity."""
import asyncio
import json
import httpx
import pytest
from auth_support import authenticated_client
from kharakteres.api import app
from kharakteres.models import LANGUAGES, LANGUAGE_SECTIONS, GenerateRequest, SpellInput, canonical_language
from kharakteres.generation import SpellGenerator, GenerationError
from kharakteres import verification


@pytest.mark.parametrize('label,code',[
    ('Italian','it'),('이탈리아어','it'),('이태리어','it'),('ita','it'),
    ('Old Church Slavonic','cu'),('Old Church Slavic','cu'),('고대 교회 슬라브어','cu'),
    ('고대교회슬라브어','cu'),('고교회슬라브어','cu'),('chu','cu'),
])
def test_aliases_reach_generation_and_storage_schema(label,code):
    assert canonical_language(label)==code
    assert GenerateRequest(prompt='방을 밝히는 주문',language=label).language==code
    assert SpellInput(name='빛',incantation='test',language=label,elements=['light'],effect='밝힌다').language==code


def test_catalog_count_and_demo_choice_match_registry(tmp_path,monkeypatch):
    monkeypatch.setenv('SPELL_DB_PATH',str(tmp_path/'spells.sqlite'))
    with authenticated_client(app) as client:
        catalog=client.get('/api/catalog').json()
        assert catalog['registered_language_count']==len(catalog['languages'])==229
        assert {s['code'] for s in catalog['languages']}>=set(LANGUAGE_SECTIONS)
        for label,code in [('Italian','it'),('고대 교회 슬라브어','cu')]:
            result=client.post('/api/language',json={'message':label})
            assert result.status_code==200,result.text
            assert result.json()['resolved'] and result.json()['language']==code
        # Choosing the language in demo is distinct from actually translating into it.
        result=client.post('/api/generate',json={'language':'cu','prompt':'작은 등불을 만드는 주문'}).json()
        assert result['draft']['language_status']=='demo_untranslated'


@pytest.mark.parametrize('code,word,name',[('it','luce','Italian'),('cu','свѣтъ','Old Church Slavonic')])
def test_new_languages_use_correct_dictionary_code_and_section(monkeypatch,code,word,name):
    monkeypatch.setenv('SPELL_DICTIONARY_PROVIDER','wiktapi')
    monkeypatch.setattr(verification,'_DENIED_HOSTS',set())
    monkeypatch.setattr(verification,'_BACKOFF_UNTIL',{})
    def handle(request):
        assert request.url.params['lang']==code
        if request.url.path.endswith('/definitions'):
            return httpx.Response(200,json={'word':word,'edition':'en','definitions':[
                {'lang_code':'en','senses':[{'glosses':['wrong language']}]},
                {'lang_code':code,'senses':[{'glosses':['light']}]}]})
        return httpx.Response(200,json={'word':word,'edition':'en','pronunciations':[]})
    result=asyncio.run(verification.verify_language({'language':code,'incantation':word},transport=httpx.MockTransport(handle)))
    assert result['status']=='references_found'
    assert result['sources'][0]['language']==name and result['sources'][0]['excerpt']=='light'
    assert name.replace(' ','_') in result['sources'][0]['origin_url']


@pytest.mark.parametrize('words,accepted',[('Свѣтъ буди.',True),('Ⱄⰲⱑⱅⱏ',True),('Light arise.',False)])
def test_old_church_slavonic_cannot_silently_be_latin_transliteration(words,accepted):
    class Store:
        def all(self): return []
    class Model:
        name='stub'
        def _chat(self,*args,**kwargs):
            return json.dumps({'name':'빛의 부름','incantation':words,'literal_meaning':'빛이 있으라',
                'effect':'작은 방을 밝힌다','hangul_pronunciation':'스볘트 부디','ipa':'/test/',
                'pronunciation_note':'재구 발음의 근사치'}),{}
    generator=SpellGenerator('openai',Model(),Store())
    req=GenerateRequest(prompt='작은 방을 밝히는 주문',language='chu').model_dump()
    action=generator.compose({'request':req,'candidates':[],'steps':[]})
    if accepted:
        assert asyncio.run(action)['draft']['language']=='cu'
    else:
        with pytest.raises(GenerationError,match='원문 문자'): asyncio.run(action)
