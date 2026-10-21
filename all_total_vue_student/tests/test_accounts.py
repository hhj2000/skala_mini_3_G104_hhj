"""Real authentication boundary, persistent account isolation and secret disposal."""
import pytest
from fastapi.testclient import TestClient
from kharakteres.api import app
from test_spells import spell

PASSWORD = 'a-long-test-password-2026'


def register(client, username):
    response = client.post('/api/auth/register', json={'username':username,'email':username+'@example.test','password':PASSWORD})
    assert response.status_code == 200, response.text
    return response


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('SPELL_DB_PATH',str(tmp_path/'legacy.sqlite'))
    monkeypatch.setenv('LLM_BACKEND','fake')
    with TestClient(app) as client:
        yield client


def test_register_duplicate_login_recovery_and_session_revocation(client):
    assert client.get('/api/spells').status_code == 401
    register(client,'alice')
    assert client.get('/api/auth/session').json()['authenticated']
    assert not client.get('/api/auth/check-id',params={'username':'ALICE'}).json()['available']
    assert client.post('/api/auth/register',json={'username':'ALICE','email':'second@example.test','password':PASSWORD}).status_code == 409
    assert client.post('/api/auth/register',json={'username':'bob','email':'ALICE@example.test','password':PASSWORD}).status_code == 409
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/spells').status_code == 401
    assert client.post('/api/auth/login',json={'username':'alice','password':'wrong'}).status_code == 401
    assert client.post('/api/auth/login',json={'username':'ALICE','password':PASSWORD}).status_code == 200
    assert client.post('/api/auth/find-id',json={'email':'alice@example.test'}).json()['username']=='alice'
    assert client.post('/api/auth/reset-password',json={'username':'alice','email':'wrong@example.test','new_password':'new-long-password-2026'}).status_code == 404
    assert client.post('/api/auth/reset-password',json={'username':'alice','email':'alice@example.test','new_password':'new-long-password-2026'}).json()['reset']
    assert client.get('/api/spells').status_code == 401
    assert client.post('/api/auth/login',json={'username':'alice','password':PASSWORD}).status_code == 401
    assert client.post('/api/auth/login',json={'username':'alice','password':'new-long-password-2026'}).status_code == 200


def test_two_accounts_cannot_read_edit_delete_or_export_each_others_spells(client):
    register(client,'alice')
    record=client.post('/api/spells',json=spell()).json()['spell']
    alice_index=app.state.auth.workspaces[1].retrieval.index.path
    client.post('/api/auth/logout')
    register(client,'bob')
    assert client.get('/api/spells').json()['total']==0
    assert client.get('/api/spells/'+record['id']).status_code==404
    assert client.put('/api/spells/'+record['id'],json={**spell(),'version':1}).status_code==404
    assert client.delete('/api/spells/'+record['id'],params={'version':1}).status_code==404
    assert client.get('/api/spells/export').json()['spells']==[]
    assert app.state.auth.workspaces[2].retrieval.index.path != alice_index
    client.post('/api/auth/logout')
    client.post('/api/auth/login',json={'username':'alice','password':PASSWORD})
    assert client.get('/api/spells').json()['total']==1


def test_secret_workspace_exit_and_logout_destroy_data(client):
    register(client,'alice')
    client.post('/api/spells',json=spell())
    for action in ('exit','logout'):
        assert client.post('/api/auth/secret/enter').status_code==200
        session=next(s for s in app.state.auth.sessions.values() if s.secret_workspace)
        path=session.secret_workspace.store.path
        assert client.get('/api/spells').json()['total']==0
        assert client.post('/api/spells',json=spell()).status_code==201
        route='/api/auth/secret/exit' if action=='exit' else '/api/auth/logout'
        assert client.post(route).status_code==200
        assert not path.parent.exists()
        if action=='logout': client.post('/api/auth/login',json={'username':'alice','password':PASSWORD})
        assert client.get('/api/spells').json()['total']==1


def test_accounts_and_spells_survive_process_lifespan(tmp_path,monkeypatch):
    monkeypatch.setenv('SPELL_DB_PATH',str(tmp_path/'legacy.sqlite'))
    monkeypatch.setenv('LLM_BACKEND','fake')
    with TestClient(app) as client:
        register(client,'alice')
        saved=client.post('/api/spells',json=spell()).json()['spell']
        old_cookie=client.cookies.get('kharakteres_session')
    with TestClient(app) as client:
        client.cookies.set('kharakteres_session',old_cookie)
        assert client.get('/api/auth/session').json()['authenticated']
        assert client.get('/api/spells/'+saved['id']).json()['id']==saved['id']
        assert client.post('/api/auth/logout').status_code==200
        client.cookies.set('kharakteres_session',old_cookie)
        assert client.get('/api/spells').status_code==401
    with TestClient(app) as client:
        client.cookies.set('kharakteres_session',old_cookie)
        assert client.get('/api/spells').status_code==401


def test_login_cookie_persists_and_refreshes_without_eight_hour_expiry(client,monkeypatch):
    import time
    import sqlite3
    from kharakteres.auth import COOKIE_MAX_AGE
    response=register(client,'alice')
    cookie=client.cookies.get('kharakteres_session')
    assert 'Max-Age='+str(COOKIE_MAX_AGE) in response.headers['set-cookie']
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
    now=time.time()
    monkeypatch.setattr(time,'time',lambda:now+9*60*60)
    response=client.get('/api/auth/session')
    assert response.json()['authenticated']
    assert 'Max-Age='+str(COOKIE_MAX_AGE) in response.headers['set-cookie']
    with sqlite3.connect(app.state.accounts.path) as db:
        hashes=db.execute('SELECT token_hash FROM login_sessions').fetchall()
    assert hashes and all(cookie.split('.')[0] not in row[0] for row in hashes)
    client.cookies.clear()
    client.cookies.set('kharakteres_session',cookie[:-1]+('0' if cookie[-1]!='0' else '1'))
    assert not client.get('/api/auth/session').json()['authenticated']


def test_secret_content_discarded_but_login_and_secret_mode_survive_restart(tmp_path,monkeypatch):
    monkeypatch.setenv('SPELL_DB_PATH',str(tmp_path/'legacy.sqlite'))
    monkeypatch.setenv('LLM_BACKEND','fake')
    with TestClient(app) as client:
        register(client,'alice')
        normal=client.post('/api/spells',json=spell()).json()['spell']
        client.post('/api/auth/secret/enter')
        secret=client.post('/api/spells',json=spell()).json()['spell']
        cookie=client.cookies.get('kharakteres_session')
    with TestClient(app) as client:
        client.cookies.set('kharakteres_session',cookie)
        info=client.get('/api/auth/session').json()
        assert info['authenticated'] and info['secret_mode']
        assert client.get('/api/spells').json()['total']==0
        assert client.get('/api/spells/'+secret['id']).status_code==404
        client.post('/api/auth/secret/exit')
        assert client.get('/api/spells/'+normal['id']).status_code==200
        client.cookies.clear();client.cookies.set('kharakteres_session',cookie)
        assert client.get('/api/spells').status_code==401


def test_password_reset_revokes_sessions_not_loaded_into_memory_after_restart(tmp_path,monkeypatch):
    monkeypatch.setenv('SPELL_DB_PATH',str(tmp_path/'legacy.sqlite'))
    monkeypatch.setenv('LLM_BACKEND','fake')
    with TestClient(app) as client:
        register(client,'alice')
        cookie=client.cookies.get('kharakteres_session')
    with TestClient(app) as client:
        assert not app.state.auth.sessions
        result=client.post('/api/auth/reset-password',json={'username':'alice','email':'alice@example.test','new_password':'new-long-password-2026'})
        assert result.status_code==200
        client.cookies.set('kharakteres_session',cookie)
        assert client.get('/api/spells').status_code==401


def test_latest_login_replaces_old_device_and_cleans_secret_workspace(client):
    register(client,'alice')
    original=client.post('/api/spells',json=spell()).json()['spell']
    old=client.cookies.get('kharakteres_session')
    client.post('/api/auth/secret/enter')
    old_session=next(s for s in app.state.auth.sessions.values() if s.secret_workspace)
    secret_path=old_session.secret_workspace.store.path.parent
    response=client.post('/api/auth/login',json={'username':'ALICE','password':PASSWORD})
    assert response.status_code==200
    latest=client.cookies.get('kharakteres_session')
    assert latest!=old and not secret_path.exists()
    assert client.get('/api/spells/'+original['id']).status_code==200
    assert client.post('/api/auth/login',json={'username':'alice','password':'wrong'}).status_code==401
    assert client.get('/api/auth/session').json()['authenticated']
    for path in ['/api/spells','/api/catalog']:
        assert client.get(path,headers={'Cookie':'kharakteres_session='+old}).status_code==401
    assert not client.get('/api/auth/session',headers={'Cookie':'kharakteres_session='+old}).json()['authenticated']
    assert client.post('/api/auth/logout',headers={'Cookie':'kharakteres_session='+old}).status_code==401
    assert client.get('/api/auth/session',headers={'Cookie':'kharakteres_session='+latest}).json()['authenticated']
    register(client,'bob')
    assert client.get('/api/auth/session',headers={'Cookie':'kharakteres_session='+latest}).json()['username']=='alice'


def test_legacy_multiple_sessions_migrate_to_latest_with_unique_account_index(tmp_path):
    import sqlite3
    from kharakteres.accounts import AccountStore
    path=tmp_path/'accounts.sqlite';store=AccountStore(path)
    account,_=store.create('alice','alice@example.test',PASSWORD)
    with sqlite3.connect(path) as db:
        db.execute('DROP INDEX one_login_per_account')
        for sid in ['older','newest']:
            db.execute('INSERT INTO login_sessions(token_hash,user_id) VALUES (?,?)',(store.session_hash(sid),account['id']))
    migrated=AccountStore(path)
    assert migrated.load_session('older') is None
    assert migrated.load_session('newest')['id']==account['id']
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO login_sessions(token_hash,user_id) VALUES (?,?)',('third-token',account['id']))


def test_parallel_logins_across_stores_leave_exactly_one_active_session(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from kharakteres.accounts import AccountStore
    path=tmp_path/'accounts.sqlite';first=AccountStore(path);second=AccountStore(path)
    account,_=first.create('alice','alice@example.test',PASSWORD)
    gate=Barrier(2)
    def save(pair):
        store,sid=pair;gate.wait();store.save_session(sid,account['id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(save,[(first,'device-a'),(second,'device-b')]))
    assert sum(first.load_session(sid) is not None for sid in ['device-a','device-b'])==1


def test_superseded_secret_rotation_cannot_replace_new_login(client):
    from fastapi import HTTPException
    register(client,'alice')
    manager=app.state.auth
    old_sid,old_session=next(iter(manager.sessions.items()))
    account={'id':old_session.user_id,'username':'alice'}
    manager.accounts.save_session('another-manager-login',account['id'])
    with pytest.raises(HTTPException) as error:
        manager.create(account,previous_sid=old_sid)
    assert error.value.status_code==401
    assert manager.accounts.load_session('another-manager-login') is not None


@pytest.mark.parametrize('method',['POST','PUT'])
def test_revoked_session_cannot_write_after_waiting_for_content_check(client,monkeypatch,method):
    register(client,'alice')
    saved=client.post('/api/spells',json=spell()).json()['spell']
    session=next(iter(app.state.auth.sessions.values()))
    async def delayed_check(*args,**kwargs):
        # Simulate another device logging in while this request awaited an LLM guard.
        app.state.auth.create({'id':session.user_id,'username':'alice'})
    monkeypatch.setattr(app.state.guard,'check',delayed_check)
    path='/api/spells' if method=='POST' else '/api/spells/'+saved['id']
    body=spell() if method=='POST' else {**spell(),'version':saved['version']}
    assert client.request(method,path,json=body).status_code==401
    workspace=app.state.auth.workspace_for(session.user_id)
    assert len(workspace.store.all())==1
    assert workspace.store.get(saved['id'])['version']==saved['version']
