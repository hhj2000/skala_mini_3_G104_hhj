"""Run INSIDE an isolated disposable container, never against a user server.

Requires LLM_BACKEND=fake and an empty /app/data tmpfs. No external APIs.
"""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from kharakteres.api import app
from kharakteres.models import SpellInput


def main():
    if os.getenv('LLM_BACKEND')!='fake' or os.getenv('KHARAKTERES_CONTAINER_SMOKE')!='1':
        raise RuntimeError('Use the isolated docker smoke command in doc/EVALUATION.md')
    password='container-test-password-2026'
    with TestClient(app) as client:
        if app.state.accounts.count():
            raise RuntimeError('Refusing an existing account registry; mount an empty tmpfs')
        assert client.get('/health').status_code==200
        assert client.get('/api/spells').status_code==401
        assert client.post('/api/auth/register',json={'username':'alice','email':'alice@example.test','password':password}).status_code==200
        spell=SpellInput(name='컨테이너 등불',incantation='빛이여 오라',effect='작은 방을 밝힌다',language='ko',elements=['light']).model_dump()
        assert client.post('/api/spells',json=spell).status_code==201
        assert client.post('/api/auth/secret/enter').status_code==200
        session=next(s for s in app.state.auth.sessions.values() if s.secret_workspace)
        secret_path=session.secret_workspace.store.path
        assert client.get('/api/spells').json()['total']==0
        assert client.post('/api/spells',json=spell).status_code==201
        assert client.post('/api/auth/secret/exit').status_code==200
        assert not secret_path.parent.exists()
        assert client.get('/api/spells').json()['total']==1
        assert client.post('/api/auth/logout').status_code==200
        assert client.post('/api/auth/login',json={'username':'alice','password':password}).status_code==200
        result=client.post('/api/generate/stream',json={'prompt':'작은 방을 밝히는 주문'})
        assert result.status_code==200 and 'event: done' in result.text
        print(json.dumps({'container':'read-only filesystem with isolated tmpfs','health':True,'auth':True,'crud':True,'secret_disposal':True,'fake_sse':True,'real_model_in_container':'not tested'}))


if __name__=='__main__': main()
