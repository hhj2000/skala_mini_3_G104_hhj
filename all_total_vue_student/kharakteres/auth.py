"""Account login, signed sessions and per-user/secret workspaces."""

from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import hmac
import os
import secrets
import sqlite3
import time

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from .accounts import AccountStore
from .workspace import active_workspace, create_secret_workspace, create_user_workspace

COOKIE = "kharakteres_session"
SESSION_TTL = 8 * 60 * 60
PUBLIC_AUTH_PATHS = {
    "/api/auth/session", "/api/auth/login", "/api/auth/register",
    "/api/auth/check-id", "/api/auth/find-id", "/api/auth/reset-password",
}


@dataclass
class AuthSession:
    expires_at: int
    user_id: int
    username: str
    secret_workspace: object = None
    in_flight: int = 0
    destroy_pending: bool = False


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=256)


class RegisterBody(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class FindIDBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordBody(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    email: str = Field(min_length=3, max_length=254)
    new_password: str = Field(min_length=12, max_length=256)


class AuthManager:
    def __init__(self, app, accounts):
        self.app = app
        self.accounts: AccountStore = accounts
        self.required = True
        key = os.getenv("KHARAKTERES_SESSION_SECRET", "")
        if os.getenv("REQUIRE_SESSION_SECRET", "0").lower() in {"1", "true", "yes"} and len(key.encode()) < 32:
            raise ValueError("32바이트 이상의 KHARAKTERES_SESSION_SECRET을 설정하세요.")
        self.key = key.encode() if key else secrets.token_bytes(32)
        self.sessions: dict[str, AuthSession] = {}
        self.workspaces = {}
        self.attempts = defaultdict(deque)
        self.secure_cookie = os.getenv("KHARAKTERES_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"}
        self.data_root = app.state.workspace.store.path.parent

    def _signature(self, sid, expiry):
        return hmac.new(self.key, f"{sid}.{expiry}".encode(), hashlib.sha256).hexdigest()

    def token(self, sid, session):
        return f"{sid}.{session.expires_at}.{self._signature(sid, session.expires_at)}"

    def identify(self, token):
        try:
            sid, expiry_text, signature = token.split(".", 2)
            expiry = int(expiry_text)
        except (ValueError, AttributeError):
            return None, None
        if expiry <= int(time.time()) or not hmac.compare_digest(signature, self._signature(sid, expiry)):
            return None, None
        session = self.sessions.get(sid)
        if session is None or session.expires_at != expiry or session.destroy_pending:
            return None, None
        return sid, session

    def create(self, account):
        sid = secrets.token_urlsafe(32)
        session = AuthSession(int(time.time()) + SESSION_TTL, account["id"], account["username"])
        self.sessions[sid] = session
        return sid, session

    def workspace_for(self, user_id):
        if user_id not in self.workspaces:
            app = self.app
            self.workspaces[user_id] = create_user_workspace(
                self.data_root, user_id, app.state.backend, app.state.quality,
                app.state.guard, app.state.retrieval.enabled,
            )
        return self.workspaces[user_id]

    def prune(self):
        now = int(time.time())
        for sid, session in list(self.sessions.items()):
            if session.expires_at <= now and not session.destroy_pending:
                self.remove(sid, session)

    def cookie(self, response, request, sid, session):
        response.set_cookie(COOKIE, self.token(sid, session), max_age=SESSION_TTL,
                            httponly=True, secure=self.secure_cookie or request.url.scheme == "https",
                            samesite="strict", path="/")
        return response

    def remove(self, sid, session):
        session.destroy_pending = True
        if session.in_flight == 0:
            self._destroy(sid, session)

    def _destroy(self, sid, session):
        if session.secret_workspace is not None:
            session.secret_workspace.close()
            session.secret_workspace = None
        self.sessions.pop(sid, None)

    def finish_request(self, sid, session):
        session.in_flight = max(0, session.in_flight - 1)
        if session.destroy_pending and session.in_flight == 0:
            self._destroy(sid, session)

    def require(self, request):
        session = getattr(request.state, "auth_session", None)
        sid = getattr(request.state, "auth_session_id", None)
        if session is None:
            raise HTTPException(401, "로그인이 필요합니다.")
        return sid, session

    def check_rate(self, request, bucket, limit=8):
        address = request.client.host if request.client else "unknown"
        now = time.monotonic()
        attempts = self.attempts[(bucket, address)]
        while attempts and now - attempts[0] > 300:
            attempts.popleft()
        if len(attempts) >= limit:
            raise HTTPException(429, "요청이 많습니다. 5분 후 다시 시도해 주세요.")
        attempts.append(now)

    def migrate_legacy_store(self, user_id):
        """Give the first registered account a copy of the former shared library."""
        source = self.app.state.workspace.store.path
        target = self.data_root / "users" / str(user_id) / "spells.sqlite"
        if not source.exists() or target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
            src.backup(dst)
        # Vector embeddings are derived data and will be rebuilt in the account index.


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        app = scope["app"]
        manager = getattr(app.state, "auth", None)
        if manager:
            manager.prune()
        path = scope.get("path", "")
        headers = dict(scope.get("headers", []))
        cookies = {}
        for piece in headers.get(b"cookie", b"").decode("latin1").split(";"):
            if "=" in piece:
                name, value = piece.strip().split("=", 1)
                cookies[name] = value
        sid, session = manager.identify(cookies.get(COOKIE, "")) if manager else (None, None)
        if manager and path.startswith("/api/") and path not in PUBLIC_AUTH_PATHS:
            if session is None:
                response = JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
                await response(scope, receive, send)
                return
            session.in_flight += 1
        workspace = None
        if session is not None:
            workspace = session.secret_workspace or manager.workspace_for(session.user_id)
        elif manager is None:
            workspace = getattr(app.state, "workspace", None)
        scope.setdefault("state", {})["auth_session"] = session
        scope["state"]["auth_session_id"] = sid
        context_token = active_workspace.set(workspace)
        try:
            if session is not None and session.secret_workspace is not None:
                from langsmith import tracing_context
                with tracing_context(enabled=False):
                    await self.app(scope, receive, send)
            else:
                await self.app(scope, receive, send)
        finally:
            active_workspace.reset(context_token)
            if session is not None and path.startswith("/api/") and path not in PUBLIC_AUTH_PATHS:
                manager.finish_request(sid, session)


async def auth_session(request: Request):
    manager = request.app.state.auth
    session = getattr(request.state, "auth_session", None)
    return {
        "auth_required": True,
        "authenticated": session is not None,
        "username": session.username if session else None,
        "secret_mode": bool(session and session.secret_workspace is not None),
        "has_accounts": manager.accounts.count() > 0,
    }


async def register(request: Request, data: RegisterBody):
    manager = request.app.state.auth
    manager.check_rate(request, "register", limit=12)
    try:
        account, first = manager.accounts.create(data.username, data.email, data.password)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    if first:
        manager.migrate_legacy_store(account["id"])
    manager.workspace_for(account["id"])
    sid, session = manager.create(account)
    return manager.cookie(JSONResponse({"authenticated": True, "username": account["username"]}), request, sid, session)


async def check_id(request: Request, username: str):
    manager = request.app.state.auth
    return {"available": manager.accounts.username_available(username)}


async def login(request: Request, data: LoginBody):
    manager = request.app.state.auth
    manager.check_rate(request, "login", limit=5)
    account = manager.accounts.authenticate(data.username, data.password)
    if account is None:
        raise HTTPException(401, "아이디 또는 비밀번호를 확인해 주세요.")
    manager.attempts.pop(("login", request.client.host if request.client else "unknown"), None)
    if manager.accounts.count() == 1:
        manager.migrate_legacy_store(account["id"])
    manager.workspace_for(account["id"])
    sid, session = manager.create(account)
    return manager.cookie(JSONResponse({"authenticated": True, "username": account["username"]}), request, sid, session)


async def find_id(request: Request, data: FindIDBody):
    manager = request.app.state.auth
    manager.check_rate(request, "recovery")
    username = manager.accounts.find_username(data.email)
    if username is None:
        raise HTTPException(404, "가입 정보와 일치하는 계정을 찾지 못했습니다.")
    return {"username": username}


async def reset_password(request: Request, data: ResetPasswordBody):
    manager = request.app.state.auth
    manager.check_rate(request, "recovery")
    try:
        updated = manager.accounts.reset_password(data.username, data.email, data.new_password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not updated:
        raise HTTPException(404, "가입 정보와 일치하는 계정을 찾지 못했습니다.")
    for sid, session in list(manager.sessions.items()):
        if session.username.casefold() == data.username.casefold():
            manager.remove(sid, session)
    return {"reset": True}


async def enter_secret_mode(request: Request):
    manager = request.app.state.auth
    _, session = manager.require(request)
    if session.secret_workspace is None:
        app = request.app
        session.secret_workspace = create_secret_workspace(
            app.state.backend, app.state.quality, app.state.guard,
            app.state.retrieval.enabled,
        )
    return {"secret_mode": True, "total_spells": 0}


async def exit_secret_mode(request: Request):
    manager = request.app.state.auth
    sid, session = manager.require(request)
    if session.secret_workspace is None:
        raise HTTPException(409, "시크릿 모드가 켜져 있지 않습니다.")
    if session.in_flight > 1:
        raise HTTPException(409, "진행 중인 요청이 끝난 뒤 시크릿 모드를 종료해 주세요.")
    manager.remove(sid, session)
    new_sid, new_session = manager.create({"id": session.user_id, "username": session.username})
    response = JSONResponse({"secret_mode": False, "discarded": True})
    return manager.cookie(response, request, new_sid, new_session)


async def logout(request: Request):
    manager = request.app.state.auth
    sid, session = manager.require(request)
    if session.in_flight > 1:
        raise HTTPException(409, "진행 중인 요청이 끝난 뒤 로그아웃해 주세요.")
    manager.remove(sid, session)
    response = JSONResponse({"authenticated": False, "secret_mode": False})
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict",
                           secure=manager.secure_cookie or request.url.scheme == "https")
    return response
