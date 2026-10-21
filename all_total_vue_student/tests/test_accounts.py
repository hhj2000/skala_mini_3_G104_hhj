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
        assert client.get('/api/spells').status_code==401
        client.cookies.clear()
        assert client.post('/api/auth/login',json={'username':'alice','password':PASSWORD}).status_code==200
        assert client.get('/api/spells/'+saved['id']).json()['id']==saved['id']
