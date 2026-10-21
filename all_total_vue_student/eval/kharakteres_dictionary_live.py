"""Live lexical-source API/save/read/browser check against an EMPTY isolated server.

Uses a disposable account; no LLM/audio APIs. The server's dictionary provider is
called for real. Never point this at an existing personal or production workspace.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kharakteres.models import SpellInput, LanguageVerification


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--browser',action='store_true')
    args=parser.parse_args()
    if args.output.exists(): parser.error('Use a new evidence file')
    base=args.base_url.rstrip('/')
    with httpx.Client(base_url=base,timeout=45) as client:
        session=client.get('/api/auth/session');session.raise_for_status()
        if session.json()['has_accounts']: raise RuntimeError('Refusing non-empty account registry')
        response=client.post('/api/auth/register',json={'username':'source_tester','email':'sources@example.test','password':'dictionary-test-password-2026'})
        response.raise_for_status()
        records=[]
        for code,word in [('en','light'),('la','lux'),('grc','φῶς'),('sa','अग्नि')]:
            payload=SpellInput(name='출처검증 '+code,incantation=word,language=code,elements=['light'],effect='웹 어휘 출처와 저장 흐름의 검증용 주문').model_dump()
            started=time.perf_counter()
            response=client.post('/api/verify-language',json=payload);response.raise_for_status()
            evidence=LanguageVerification.model_validate(response.json())
            assert evidence.status=='references_found',response.text
            assert evidence.provider.startswith('WiktAPI'),evidence.provider
            assert evidence.sources and evidence.sources[0].language in ['English','Latin','Ancient Greek','Sanskrit']
            payload['verification']=evidence.model_dump()
            saved=client.post('/api/spells',json=payload);saved.raise_for_status()
            saved=saved.json()['spell']
            reread=client.get('/api/spells/'+saved['id']);reread.raise_for_status()
            assert reread.json()['verification']['sources']==payload['verification']['sources']
            records.append({'language':code,'word':word,'latency_ms':1000*(time.perf_counter()-started),'verification':evidence.model_dump(),'saved_and_read':True})
        browser_result=None
        if args.browser:
            from playwright.sync_api import sync_playwright,expect
            with sync_playwright() as playwright:
                chrome=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
                browser=playwright.chromium.launch(headless=True,**({'executable_path':str(chrome)} if chrome.exists() else {}))
                context=browser.new_context(viewport={'width':1440,'height':1080})
                context.add_cookies([{'name':'kharakteres_session','value':client.cookies.get('kharakteres_session'),'url':base}])
                page=context.new_page();errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base)
                page.locator('.spell-card').filter(has_text='출처검증 en').click()
                source=page.locator('.source-evidence').filter(has_text='WiktAPI')
                expect(source).to_be_visible()
                expect(source.get_by_text('원 사전 항목 · 현재 판본 ↗',exact=True)).to_be_visible()
                expect(source).to_contain_text('판본 미고정')
                assert source.locator('a').first.get_attribute('href').startswith('https://api.wiktapi.dev/')
                screenshot=args.output.with_suffix('.png')
                screenshot.parent.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(screenshot),full_page=True)
                assert not errors,errors
                browser_result={'vue_source_component':True,'provider_attribution':True,'origin_link':True,'page_errors':errors,'screenshot':str(screenshot)}
                browser.close()
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'scope':'isolated Docker HTTP API + persistence + optional Vue rendering; real dictionary, no LLM/audio calls','records':records,'browser':browser_result}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'languages':[r['language'] for r in records],'status':'passed','browser':browser_result is not None,'output':str(args.output)},ensure_ascii=False))


if __name__=='__main__':main()
