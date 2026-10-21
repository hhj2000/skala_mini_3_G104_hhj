"""Legacy feature tests now authenticate through the real registration endpoint."""
from contextlib import contextmanager
from fastapi.testclient import TestClient


@contextmanager
def authenticated_client(app):
    with TestClient(app) as client:
        response = client.post('/api/auth/register', json={
            'username': 'feature_tester', 'email': 'feature@example.test',
            'password': 'feature-test-password-2026',
        })
        assert response.status_code == 200, response.text
        account_id = next(iter(app.state.auth.workspaces))
        workspace = app.state.auth.workspaces[account_id]
        # Old tests inject model/retrieval fakes via these convenience references.
        # Request auth and per-account workspace resolution remain fully enabled.
        app.state.generator = workspace.generator
        app.state.retrieval = workspace.retrieval
        app.state.store = workspace.store
        yield client
