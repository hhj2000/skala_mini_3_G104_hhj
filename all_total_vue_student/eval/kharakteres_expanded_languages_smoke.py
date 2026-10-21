"""Live language-catalog/lexical API + desktop/mobile Vue check on an empty server.

The test registers its own account. Configure an isolated temporary DB and rules-only
content guard; no generation or voice APIs are invoked. Never use a personal server.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import httpx
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kharakteres.models import SpellInput, LanguageVerification


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--refresh',action='store_true')
    args=p.parse_args()
    if args.output.exists():p.error('Use a new output file')
    base=args.base_url.rstrip('/')
    with httpx.Client(base_url=base,timeout=45) as client:
        info=client.get('/api/auth/session');info.raise_for_status()
        if info.json()['has_accounts']:raise RuntimeError('Refusing non-empty account registry')
        result=client.post('/api/auth/register',json={'username':'catalog_tester','email':'catalog@example.test','password':'expanded-language-test-2026'})
        result.raise_for_status()
        catalog=client.get('/api/catalog').json()
        assert catalog['language_catalog']['total']==catalog['registered_language_count']==len(catalog['languages'])==229
        assert client.get('/api/languages',params={'q':'Klingon'}).json()['total']==0
        all_rows=client.get('/api/languages',params={'limit':200}).json()['items']+client.get('/api/languages',params={'offset':200,'limit':200}).json()['items']
        assert len(all_rows)==229
        assert [r['name'] for r in all_rows]==sorted(r['name'] for r in all_rows)
        assert all(any('가'<=c<='힣' for c in r['name']) for r in all_rows)
        refreshed=None
        if args.refresh:
            result=client.post('/api/languages/refresh');result.raise_for_status();refreshed=result.json()
            assert refreshed['source']=='live' and not refreshed['last_refresh_error'],refreshed
        records=[]
        for name,code,word in [('Portuguese','pt','luz'),('Finnish','fi','valo'),('Hebrew','he','אור')]:
            found=client.get('/api/languages',params={'q':name}).json()
            assert any(row['code']==code for row in found['items']),found
            body=SpellInput(name='목록 검증 '+code,incantation=word,language=name,elements=['light'],effect='작은 방을 비추는 빛의 검증용 주문').model_dump()
            response=client.post('/api/verify-language',json=body);response.raise_for_status()
            evidence=LanguageVerification.model_validate(response.json())
            assert evidence.status=='references_found',response.text
            assert evidence.sources[0].language==name
            body['verification']=evidence.model_dump()
            response=client.post('/api/spells',json=body);response.raise_for_status();saved=response.json()['spell']
            assert client.get('/api/spells/'+saved['id']).json()['language']==code
            records.append({'code':code,'verification':evidence.model_dump(),'saved_and_read':True})
        with sync_playwright() as playwright:
            chrome=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            browser=playwright.chromium.launch(headless=True,**({'executable_path':str(chrome)} if chrome.exists() else {}))
            context=browser.new_context(viewport={'width':1440,'height':1080})
            context.add_cookies([{'name':'kharakteres_session','value':client.cookies.get('kharakteres_session'),'url':base}])
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base)
            page.locator('nav').get_by_role('button',name='언어 목록',exact=False).click()
            expect(page.locator('.language-card')).to_have_count(48)
            expect(page.locator('.create-title')).to_contain_text('지원 언어 229개')
            controls=['#language-catalog-search','#language-catalog-family','.language-filter','.language-refresh']
            boxes=[page.locator(selector).bounding_box() for selector in controls]
            assert max(box['y'] for box in boxes)-min(box['y'] for box in boxes)<2,boxes
            assert max(box['height'] for box in boxes)-min(box['height'] for box in boxes)<2,boxes
            family=page.locator('#language-catalog-family')
            expect(family.locator('option')).to_have_text(['모든 분류','현대 언어','고전 언어','사멸 언어'])
            family.select_option('C')
            expect(page.locator('.language-card')).to_have_count(17)
            expect(page.locator('.language-card').first).to_contain_text('고전 언어')
            family.select_option('')
            expect(page.locator('.language-card')).to_have_count(48)
            # Race: a later query must win over earlier in-flight search results.
            page.locator('#language-catalog-search').fill('Hebrew')
            page.locator('#language-catalog-search').fill('Finnish')
            card=page.locator('.language-card').filter(has_text='핀란드어').first
            expect(card).to_be_visible()
            assert 'Finnish' in card.inner_text()
            args.output.parent.mkdir(parents=True,exist_ok=True)
            desktop=args.output.with_suffix('.png');page.screenshot(path=str(desktop),full_page=True)
            card.get_by_role('button',name='이 언어로 만들기').click()
            expect(page.locator('.language-chat')).to_contain_text('핀란드어')
            page.locator('#prompt').fill('작은 방을 밝히는 짧은 주문')
            expect(page.get_by_role('button',name='✦ 주문 생성하기',exact=True)).to_be_enabled()
            # Do not generate: this test deliberately makes no LLM requests.
            page.set_viewport_size({'width':390,'height':844})
            page.locator('nav').get_by_role('button',name='언어 목록',exact=False).click()
            page.locator('#language-catalog-search').fill('Hebrew')
            expect(page.locator('.language-card').first).to_contain_text('히브리어')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'mobile horizontal overflow'
            mobile=args.output.with_name(args.output.stem+'-mobile.png');page.screenshot(path=str(mobile),full_page=True)
            assert not errors,errors
            # A fresh browser context restores the persistent cookie and stays signed in.
            state=context.storage_state()
            cookie=next(c for c in state['cookies'] if c['name']=='kharakteres_session')
            assert cookie['expires']>0 and cookie['httpOnly']
            context.close()
            restored=browser.new_context(storage_state=state)
            restored_page=restored.new_page();restored_page.goto(base)
            expect(restored_page.get_by_role('button',name='로그아웃',exact=True)).to_be_visible()
            browser.close()
    args.output.write_text(json.dumps({'checked_at':datetime.now(timezone.utc).isoformat(),'scope':'isolated server, real provider metadata/word lookups, API persistence, desktop/mobile Vue; no generation/audio calls',
        'catalog':catalog['language_catalog'],'refresh':refreshed,'records':records,'browser':{'errors':errors,'desktop':str(desktop),'mobile':str(mobile),'pick_to_creation':True,'no_horizontal_overflow':True,'korean_names_only':True,'korean_alphabetical_order':True,'desktop_controls_aligned':True,'classical_filter_merged':True,'browser_context_session_restored':True}},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':'passed','catalog':catalog['language_catalog']['total'],'languages':[r['code'] for r in records],'output':str(args.output)}))


if __name__=='__main__':main()
