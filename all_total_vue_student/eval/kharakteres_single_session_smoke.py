"""Isolated two-browser single-account login test; refuses an existing account DB.

No model, dictionary or audio calls. Output contains no credentials/session tokens.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect

PASSWORD='single-session-smoke-2026'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Use a new output path')
    base=args.base_url.rstrip('/')
    with httpx.Client(base_url=base,timeout=20) as api:
        session=api.get('/api/auth/session');session.raise_for_status()
        if session.json()['has_accounts']:raise RuntimeError('Refusing existing account registry')
        response=api.post('/api/auth/register',json={'username':'single_tester','email':'single@example.test','password':PASSWORD})
        response.raise_for_status()
        old=api.cookies.get('kharakteres_session')
        with sync_playwright() as playwright:
            chrome=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            browser=playwright.chromium.launch(headless=True,**({'executable_path':str(chrome)} if chrome.exists() else {}))
            a=browser.new_context(viewport={'width':1440,'height':1000})
            a.add_cookies([{'name':'kharakteres_session','value':old,'url':base}])
            first=a.new_page();errors=[];first.on('pageerror',lambda e:errors.append(str(e)))
            first.goto(base);expect(first.get_by_role('button',name='로그아웃',exact=True)).to_be_visible()
            b=browser.new_context(viewport={'width':1440,'height':1000})
            second=b.new_page();second.on('pageerror',lambda e:errors.append(str(e)))
            second.goto(base)
            second.locator('#login-username').fill('single_tester')
            second.locator('#login-password').fill(PASSWORD)
            second.get_by_role('button',name='로그인',exact=True).click()
            expect(second.get_by_role('button',name='로그아웃',exact=True)).to_be_visible()
            latest=next(c['value'] for c in b.cookies() if c['name']=='kharakteres_session')
            assert latest!=old
            # Focus checks immediately, independently of the 15-second periodic check.
            first.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(first.locator('.login-screen')).to_be_visible()
            expect(first.locator('.login-screen [role=alert]')).to_contain_text('다른 기기')
            assert api.get('/api/spells',headers={'Cookie':'kharakteres_session='+old}).status_code==401
            assert api.post('/api/auth/login',json={'username':'single_tester','password':'incorrect'}).status_code==401
            assert api.get('/api/auth/session',headers={'Cookie':'kharakteres_session='+latest}).json()['authenticated']
            # A different account must not evict the currently active user.
            response=api.post('/api/auth/register',json={'username':'other_tester','email':'other@example.test','password':PASSWORD})
            response.raise_for_status()
            assert api.get('/api/auth/session',headers={'Cookie':'kharakteres_session='+latest}).json()['username']=='single_tester'
            args.output.parent.mkdir(parents=True,exist_ok=True)
            screenshot=args.output.with_suffix('.png');first.screenshot(path=str(screenshot),full_page=True)
            assert not errors,errors
            browser.close()
    args.output.write_text(json.dumps({'checked_at':datetime.now(timezone.utc).isoformat(),'scope':'isolated API and two independent Chromium browser contexts; no model/voice calls','latest_login_replaced_previous':True,'old_token_rejected':True,'old_browser_returned_to_login':True,'failed_password_preserved_active_session':True,'other_account_did_not_evict_user':True,'browser_errors':errors,'screenshot':str(screenshot)},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':'passed','output':str(args.output)}))


if __name__=='__main__':main()
