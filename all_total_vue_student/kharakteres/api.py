"""Kharakteres HTTP API와 통합 화면: 계정별 주문·생성·검색·음성·SSE.

생성 초안은 사용자가 확인해 저장하며, 요청마다 계정/시크릿 저장소를 선택한다.
계정당 최신 로그인 하나를 유지하고 비동기 검사 후 저장 직전에도 세션을 확인한다.
언어 목록은 한국어 이름 기반 가나다순이며 고대/역사는 고전 분류로 통합한다.
핵심 함수 정량 평가와 전체 HTTP·UI·실제 음성 검증 범위는 구분한다.
현재 검증 상태는 doc/EVALUATION.md와 doc/ASSIGNMENT_REVIEW.md를 참고한다.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Response, Request
from fastapi.responses import FileResponse, StreamingResponse
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from .generation import GenerationError, SpellGenerator
from .lexicon import review, search, stats
from .language_catalog import CATALOG
from .models import (
    ELEMENTS,
    LANGUAGES,
    SCHOOLS,
    TONES,
    GenerateRequest,
    LanguageRequest,
    ReviewRequest,
    SaveSpell,
    SpellInput,
    UpdateSpell,
)
from .store import SpellStore, StaleVersion
from .config import prepare_spell_storage
from .verification import invalidate_changed_evidence, verify_language

from .speech import SpeechService, SpeechRequest, MAX_AUDIO_BYTES, MIME_EXT

from .safety import ContentGuard, ContentBlocked, SafetyUnavailable, spell_content
from .retrieval import SpellRetrieval
from .streaming import event_sink, emit, STAGES, trace_event
from .workspace import Workspace, active_workspace
from .auth import (
    AuthManager, AuthMiddleware, LoginBody, RegisterBody, FindIDBody,
    ResetPasswordBody, auth_session, login, register, check_id, find_id,
    reset_password, enter_secret_mode, exit_secret_mode, logout,
)
from .accounts import AccountStore

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(app):
    from agent.model_factory import _build_llms

    backend, fast, quality = _build_llms(mode="improved")
    # An instance-local budget leaves incident/baseline settings unchanged.
    quality.num_predict = int(os.getenv("SPELL_MAX_TOKENS", "1536"))
    store = SpellStore(prepare_spell_storage())
    app.state.guard = ContentGuard(backend, quality if backend == "ollama" else fast)
    retrieval = SpellRetrieval(
        store,
        enabled=os.getenv("SPELL_VECTOR_ENABLED", "0" if backend == "fake" else "1")
        == "1",
    )
    generator = SpellGenerator(backend, quality, store, guard=app.state.guard, retrieval=retrieval)
    app.state.workspace = Workspace(store, retrieval, generator)
    app.state.store = store
    app.state.retrieval = retrieval
    app.state.generator = generator
    app.state.backend = backend
    app.state.fast = fast
    app.state.quality = quality
    app.state.write_lock = asyncio.Lock()
    app.state.accounts = AccountStore(store.path.parent / "accounts.sqlite")
    app.state.auth = AuthManager(app, app.state.accounts)
    app.state.speech = SpeechService(
        os.getenv("SPEECH_BACKEND", "disabled" if backend == "fake" else "openai")
    )
    try:
        yield
    finally:
        app.state.auth.close()
        store.close()
        from langsmith.run_trees import get_cached_client

        get_cached_client().flush()


app = FastAPI(title="Kharakteres · 나만의 마법 주문사전", lifespan=lifespan)
app.add_middleware(AuthMiddleware)


def workspace():
    return active_workspace.get() or app.state.workspace


@app.get("/api/auth/session")
async def get_auth_session(request: Request):
    return await auth_session(request)


@app.post("/api/auth/login")
async def post_login(request: Request, data: LoginBody):
    return await login(request, data)


@app.post("/api/auth/register")
async def post_register(request: Request, data: RegisterBody):
    return await register(request, data)


@app.get("/api/auth/check-id")
async def get_check_id(request: Request, username: str = Query(min_length=1, max_length=32)):
    return await check_id(request, username)


@app.post("/api/auth/find-id")
async def post_find_id(request: Request, data: FindIDBody):
    return await find_id(request, data)


@app.post("/api/auth/reset-password")
async def post_reset_password(request: Request, data: ResetPasswordBody):
    return await reset_password(request, data)


@app.post("/api/auth/secret/enter")
async def post_secret_enter(request: Request):
    return await enter_secret_mode(request)


@app.post("/api/auth/secret/exit")
async def post_secret_exit(request: Request):
    return await exit_secret_mode(request)


@app.post("/api/auth/logout")
async def post_logout(request: Request):
    return await logout(request)


@app.exception_handler(GenerationError)
async def generation_error(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": exc.message}, status_code=exc.status)


@app.exception_handler(ContentBlocked)
async def content_blocked(request, exc):
    from fastapi.responses import JSONResponse

    labels = {
        "profanity": "욕설·모욕",
        "hate": "혐오·비하",
        "politics": "현실 정치 발언",
    }
    return JSONResponse(
        {
            "detail": {
                "code": "content_blocked",
                "category": exc.category,
                "stage": exc.stage,
                "message": f"{labels.get(exc.category, '부적절한 내용')}이 포함되어 처리하지 않았습니다. 마법 창작에 맞게 내용을 바꿔 주세요.",
            }
        },
        status_code=422,
    )


@app.exception_handler(SafetyUnavailable)
async def safety_unavailable(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        {
            "detail": "콘텐츠 검사를 완료하지 못해 요청을 중단했습니다. 모델 연결을 확인하고 다시 시도해 주세요."
        },
        status_code=503,
    )


from fastapi.staticfiles import StaticFiles

app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")


@app.get("/")
async def index():
    return FileResponse(ROOT / "web_chat.html")


@app.get("/health")
async def health(request: Request):
    return {
        "status": "ok",
        "service": "kharakteres",
        "agent_mode": "spell-lexicon",
        "llm_backend": app.state.backend,
        "fast_llm": app.state.fast.name,
        "quality_llm": app.state.quality.name,
        "total_spells": (len(workspace().store.all())
                         if not app.state.auth.required or getattr(request.state, "auth_session", None)
                         else None),
    }


@app.get("/api/catalog")
async def catalog():
    return {
        "languages": [{k:r[k] for k in ("code","name","family")} for r in CATALOG.ordered],
        "registered_language_count": CATALOG.metadata()["total"],
        "language_catalog": CATALOG.metadata(),
        "language_labels": {r["code"]:r["name"] for r in CATALOG.ordered},
        "elements": ELEMENTS,
        "schools": SCHOOLS,
        "tones": TONES,
        "service": "Kharakteres",
        "backend": app.state.backend,
        "audio": app.state.speech.configuration(),
        "safety": app.state.guard.configuration(),
        "retrieval": {
            "enabled": workspace().retrieval.enabled,
            "model": workspace().retrieval.index.model_name,
        },
    }


@app.get("/api/languages")
async def list_languages(q: str=Query(default="",max_length=160), family: str=Query(default="",pattern="^([LCAHE])?$"),
                         tier: str=Query(default="",pattern="^(default|extended)?$"), dictionary_only: bool=False,
                         offset: int=Query(default=0,ge=0,le=20000), limit: int=Query(default=48,ge=1,le=200)):
    return CATALOG.search(q,family,tier,dictionary_only,offset,limit)


@app.post("/api/languages/refresh")
async def refresh_languages():
    return await CATALOG.refresh()


@app.get("/api/spells/export")
async def export():
    data = {"format": "kharakteres-lexicon-v1", "spells": workspace().store.all()}
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="kharakteres-lexicon.json"'
        },
    )


@app.get("/api/spells")
async def list_spells(
    q: str = Query(default="", max_length=200),
    language: str = "",
    element: str = "",
    school: str = "",
    world: str = "",
    search_mode: Literal["text", "semantic"] = "text",
):
    await app.state.guard.check(q, "search_query")
    current = workspace()
    all_spells = current.store.all()
    items = search(all_spells, q, language, element, school, world)
    retrieval = {"mode": "text", "reason": None}
    actual_mode = "text"
    if search_mode == "semantic" and q.strip():
        eligible = search(all_spells, "", language, element, school, world)
        items, retrieval = await current.retrieval.search(q, eligible, limit=30)
        actual_mode = "semantic"
        if retrieval["mode"] == "metadata_fallback":
            items = search(eligible, q)
            actual_mode = "text_fallback"
    return {
        "items": items,
        "total": len(items),
        "stats": stats(all_spells),
        "worlds": sorted({s["world"] for s in all_spells}),
        "search_mode": actual_mode,
        "retrieval": retrieval,
        "available_languages": sorted({s["language"] for s in all_spells}),
    }


@app.get("/api/spells/{spell_id}")
async def get_spell(spell_id: str):
    result = workspace().store.get(spell_id)
    if not result:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    return result


@app.post("/api/spells", status_code=201)
async def create_spell(data: SaveSpell, request: Request):
    await app.state.guard.check(spell_content(data.model_dump()), "save")
    payload = SpellInput.model_validate(
        data.model_dump(exclude={"acknowledge_conflicts"})
    ).model_dump()
    invalidate_changed_evidence(payload)
    if payload.get("language_kind") == "constructed":
        payload["verification"] = await verify_language(payload)
    current = workspace()
    async with app.state.write_lock:
        app.state.auth.require(request)
        conflicts = review(payload, current.store.all())
        if conflicts["has_high"] and not data.acknowledge_conflicts:
            raise HTTPException(
                409,
                {
                    "code": "conflict_review_required",
                    "message": "같은 세계관의 중복 주문을 검토한 뒤 저장해 주세요.",
                    "conflicts": conflicts,
                },
            )
        return {"spell": current.store.create(payload), "conflicts": conflicts}


@app.put("/api/spells/{spell_id}")
async def update_spell(spell_id: str, data: UpdateSpell, request: Request):
    await app.state.guard.check(spell_content(data.model_dump()), "save")
    payload = SpellInput.model_validate(
        data.model_dump(exclude={"acknowledge_conflicts", "version"})
    ).model_dump()
    invalidate_changed_evidence(payload)
    if payload.get("language_kind") == "constructed":
        payload["verification"] = await verify_language(payload)
    current = workspace()
    async with app.state.write_lock:
        app.state.auth.require(request)
        existing = current.store.get(spell_id)
        if not existing:
            raise HTTPException(404, "주문을 찾을 수 없습니다.")
        if existing["version"] != data.version:
            raise HTTPException(
                409,
                {
                    "code": "stale_version",
                    "message": "다른 화면에서 수정된 주문입니다. 새로 불러온 후 수정하세요.",
                },
            )
        conflicts = review(payload, current.store.all(), spell_id)
        if conflicts["has_high"] and not data.acknowledge_conflicts:
            raise HTTPException(
                409,
                {
                    "code": "conflict_review_required",
                    "conflicts": conflicts,
                    "message": "중복 검토 후 저장해 주세요.",
                },
            )
        try:
            result = current.store.update(spell_id, payload, data.version)
        except StaleVersion:
            raise HTTPException(409, "더 최신 수정본이 있습니다.") from None
        await asyncio.to_thread(current.retrieval.index.forget, spell_id)
        return {"spell": result, "conflicts": conflicts}


@app.delete("/api/spells/{spell_id}", status_code=204)
async def delete_spell(spell_id: str, request: Request, version: int = Query(ge=1)):
    current = workspace()
    async with app.state.write_lock:
        app.state.auth.require(request)
        try:
            deleted = current.store.delete(spell_id, version)
        except StaleVersion:
            raise HTTPException(
                409, "더 최신 수정본이 있습니다. 다시 불러오세요."
            ) from None
        if not deleted:
            raise HTTPException(404, "이미 삭제되었거나 존재하지 않는 주문입니다.")
    await asyncio.to_thread(current.retrieval.index.forget, spell_id)
    return Response(status_code=204)


@app.post("/api/generate")
@traceable(name="kharakteres.generate_request")
async def generate(data: GenerateRequest):
    return await run_generation(data)


async def run_generation(data):
    run = get_current_run_tree()
    await emit("accepted", langsmith_run_id=str(run.id) if run else None,
               stages=[{"stage": key, "label": label} for key, label in STAGES.items()],
               token_stream=app.state.backend != "fake" and data.language_kind != "constructed")
    await emit("stage", stage="input_safety", label=STAGES["input_safety"], status="running")
    await app.state.guard.check(data.model_dump(), "generation_input")
    await emit("stage", stage="input_safety", label=STAGES["input_safety"], status="completed")
    trace_event("stage_completed", stage="input_safety")
    result = await workspace().generator.generate(data)
    run = get_current_run_tree()
    return {
        "draft": result["draft"],
        "conflicts": result["conflicts"],
        "steps": result["steps"],
        "model": result["model"],
        "retrieval": result.get("retrieval"),
        "langsmith_run_id": str(run.id) if run else None,
        "warning": "작가가 직접 정의한 언어입니다. 원문·발음·의미를 그대로 사용합니다. IPA는 선택 사항입니다."
        if data.language_kind == "constructed"
        else "AI 창작 주문입니다. 특히 고전 언어의 문법·발음·의미는 별도 검수가 필요합니다. 웹 출처는 단어 항목의 참고 근거이며 문장 전체를 검증한 번역이 아닙니다.",
    }


@traceable(name="kharakteres.generate_stream_request")
async def traced_stream_generation(data):
    return await run_generation(data)


@app.post("/api/generate/stream", response_class=StreamingResponse,
          responses={200: {"content": {"text/event-stream": {}}}})
async def generate_stream(data: GenerateRequest, request: Request):
    # Bounded, per-request queue: slow clients cannot accumulate unlimited tokens.
    queue = asyncio.Queue(maxsize=64)

    async def produce():
        token = event_sink.set(queue.put)
        try:
            result = await traced_stream_generation(data)
            await emit("done", **result)
        except ContentBlocked as exc:
            await emit("error", code="content_blocked", category=exc.category,
                       message="서비스 정책에 따라 이 내용을 처리할 수 없습니다.", clear_preview=True)
        except SafetyUnavailable:
            await emit("error", code="safety_unavailable",
                       message="콘텐츠 검사를 완료하지 못했습니다. 모델 연결을 확인하고 다시 시도해 주세요.", clear_preview=True)
        except GenerationError as exc:
            await emit("error", code="generation_failed", message=exc.message, clear_preview=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            await emit("error", code="generation_failed",
                       message="생성 중 오류가 발생했습니다. 저장하지 않았으니 다시 시도해 주세요.", clear_preview=True)
        finally:
            event_sink.reset(token)

    async def events():
        task = asyncio.create_task(produce())
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                kind = event.pop("event")
                yield f"event: {kind}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if kind in {"done", "error"}:
                    break
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no",
    })


@app.post("/api/review")
async def review_spell(data: ReviewRequest):
    await app.state.guard.check(spell_content(data.model_dump()), "review_input")
    payload = data.model_dump(exclude={"exclude_id", "use_ai"})
    current = workspace()
    result = review(payload, current.store.all(), data.exclude_id)
    if data.use_ai:
        ai = await current.generator.ai_review(payload, data.exclude_id)
        result["issues"] += ai["findings"]
        result["ai_review"] = {k: v for k, v in ai.items() if k != "findings"}
    return result


@app.post("/api/language")
async def choose_language(data: LanguageRequest):
    await app.state.guard.check(data.model_dump(), "language_input")
    result = await workspace().generator.resolve_language(
        data.message, [m.model_dump() for m in data.history]
    )
    await app.state.guard.check(result.reply, "language_output")
    return {**result.model_dump(), "model": app.state.quality.name}


@app.post("/api/verify-language")
async def verify_spell_language(data: SpellInput):
    await app.state.guard.check(spell_content(data.model_dump()), "verification_input")
    return await verify_language(data.model_dump(), demo=app.state.backend == "fake")


@app.post("/api/audio/transcribe")
async def transcribe_audio(
    request: Request, language: str = Query(default="ko", pattern=r"^(|[a-z]{2})$")
):
    app.state.speech.require_enabled()
    mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime not in MIME_EXT:
        raise HTTPException(
            415,
            "지원하지 않는 오디오 형식입니다. WAV·MP3·M4A·WebM·OGG·FLAC 파일을 사용해 주세요.",
        )
    body = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_AUDIO_BYTES:
                    raise HTTPException(413, "음성 파일은 10MB 이하여야 합니다.")
                body.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, "음성 업로드 시간이 초과되었습니다.") from None
    if not body:
        raise HTTPException(422, "녹음 또는 음성 파일이 비어 있습니다.")
    result = await app.state.speech.transcribe(bytes(body), mime, language)
    await app.state.guard.check(result["text"], "stt_output")
    return result


@app.post("/api/audio/speech")
async def synthesize_audio(data: SpeechRequest, request: Request):
    await app.state.guard.check(data.text, "tts_input")
    audio = await app.state.speech.synthesize(
        data, is_disconnected=request.is_disconnected
    )
    return Response(
        audio,
        media_type="audio/wav",
        headers={
            "Content-Disposition": 'attachment; filename="kharakteres-speech.wav"',
            "Cache-Control": "no-store",
        },
    )
