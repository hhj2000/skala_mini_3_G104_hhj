"""AIDubsar audio workflow adapted to HTTP: Whisper STT and optional speech synthesis.

No notebook is executed, no example replaces failed STT, and no audio is persisted.
"""

import asyncio
import io
import os
import wave
from typing import Literal

import httpx
from langsmith import traceable
from pydantic import BaseModel, ConfigDict, Field

from .generation import GenerationError

VOICES = ["coral", "alloy", "echo", "fable", "nova", "onyx", "shimmer"]
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_WAV_BYTES = 60 * 1024 * 1024
MIME_EXT = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "video/mp4": "mp4",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
}


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=14000)
    voice: Literal["coral", "alloy", "echo", "fable", "nova", "onyx", "shimmer"] = (
        "coral"
    )
    speed: float = Field(default=1, ge=0.5, le=1.5)


def split_speech(text):
    """Keep every character; bound UTF-8 bytes as well as the provider's char limit."""
    chunks, current, size = [], "", 0
    for char in text:
        count = len(char.encode("utf-8"))
        if size + count > 1800:
            chunks.append(current)
            current, size = "", 0
        current += char
        size += count
    if current:
        chunks.append(current)
    return chunks


def combine_wav(parts):
    frames, expected = [], None
    total = 0
    for part in parts:
        with wave.open(io.BytesIO(part), "rb") as audio:
            params = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate())
            if expected and params != expected:
                raise ValueError("Inconsistent audio format")
            expected = params
            data = audio.readframes(audio.getnframes())
            total += len(data)
            if total > MAX_WAV_BYTES:
                raise ValueError("Audio output too large")
            frames.append(data)
    if not expected:
        raise ValueError("No speech returned")
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(expected[0])
        audio.setsampwidth(expected[1])
        audio.setframerate(expected[2])
        for data in frames:
            audio.writeframes(data)
    return output.getvalue()


def provider_error(exc):
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return GenerationError(
            "음성 처리 시간이 초과되었습니다. 짧게 나눠 다시 시도해 주세요.", 504
        )
    status = (
        exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    )
    message = {
        401: "음성 API 인증에 실패했습니다. OPENAI_API_KEY를 확인하세요.",
        429: "음성 API 사용량 또는 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.",
        400: "음성 API가 입력을 읽지 못했습니다. 파일 형식이나 텍스트를 확인해 주세요.",
    }.get(
        status, "음성 처리를 완료하지 못했습니다. 연결과 오디오 파일을 확인해 주세요."
    )
    return GenerationError(message)


class SpeechService:
    def __init__(self, backend="openai", transport=None):
        self.backend = backend
        self.key = os.getenv("OPENAI_API_KEY", "")
        self.stt_model = os.getenv("SPEECH_STT_MODEL", "whisper-1")
        self.tts_model = os.getenv("SPEECH_TTS_MODEL", "gpt-4o-mini-tts")
        self.transport = transport
        self.semaphore = asyncio.Semaphore(2)

    def configuration(self):
        return {
            "enabled": self.backend == "openai" and bool(self.key),
            "provider": "OpenAI",
            "stt_model": self.stt_model,
            "tts_model": self.tts_model,
            "voices": VOICES,
            "max_upload_bytes": MAX_AUDIO_BYTES,
            "note": "STT·TTS는 OpenAI API를 사용합니다. Ollama 실행 중에도 외부 전송과 API 과금이 발생합니다. 생성 음성은 AI 음성입니다.",
        }

    def require_enabled(self):
        if self.backend != "openai":
            raise GenerationError(
                "현재 모드는 음성 API를 사용하지 않습니다. 실제 실행 모드에서 확인해 주세요.",
                503,
            )
        if not self.key:
            raise GenerationError(
                "음성 기능에 OPENAI_API_KEY가 필요합니다. 서버 설정 후 다시 실행해 주세요.",
                503,
            )

    @traceable(
        name="audio.transcribe",
        process_inputs=lambda data: {
            "mime": data.get("mime"),
            "bytes": len(data.get("content", b"")),
            "language": data.get("language"),
        },
    )
    async def transcribe(self, content, mime, language="ko"):
        self.require_enabled()
        data = {"model": self.stt_model, "response_format": "json"}
        if language:
            data["language"] = language
        try:
            async with (
                self.semaphore,
                httpx.AsyncClient(timeout=90, transport=self.transport) as client,
            ):
                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.key}"},
                    data=data,
                    files={"file": (f"spell_audio.{MIME_EXT[mime]}", content, mime)},
                )
                response.raise_for_status()
                text = response.json().get("text", "").strip()
                if not text:
                    raise GenerationError(
                        "음성을 인식하지 못했습니다. 녹음 상태를 확인하고 다시 시도해 주세요.",
                        422,
                    )
                return {"text": text, "model": self.stt_model}
        except (httpx.HTTPError, ValueError, KeyError, AttributeError) as exc:
            raise provider_error(exc) from None

    @traceable(
        name="audio.synthesize",
        process_inputs=lambda data: {
            "request": data["request"].model_dump(exclude={"text"}),
            "characters": len(data["request"].text),
        },
        process_outputs=lambda data: {
            "bytes": len(data.get("output", b""))
            if isinstance(data, dict)
            else len(data)
        },
    )
    async def synthesize(self, request: SpeechRequest, is_disconnected=None):
        self.require_enabled()
        parts = []
        try:
            async with (
                asyncio.timeout(240),
                self.semaphore,
                httpx.AsyncClient(timeout=90, transport=self.transport) as client,
            ):
                for chunk in split_speech(request.text):
                    if is_disconnected and await is_disconnected():
                        raise GenerationError("음성 요청이 취소되었습니다.", 499)
                    payload = {
                        "model": self.tts_model,
                        "voice": request.voice,
                        "input": chunk,
                        "response_format": "wav",
                        "speed": request.speed,
                    }
                    if self.tts_model.startswith("gpt-"):
                        payload["instructions"] = (
                            "입력한 내용을 또렷하게 그대로 읽으세요. 내용을 추가하거나 설명하지 마세요."
                        )
                    response = await client.post(
                        "https://api.openai.com/v1/audio/speech",
                        headers={"Authorization": f"Bearer {self.key}"},
                        json=payload,
                    )
                    response.raise_for_status()
                    parts.append(response.content)
                    if sum(len(p) for p in parts) > MAX_WAV_BYTES:
                        raise ValueError("Audio output too large")
                return combine_wav(parts)
        except (
            TimeoutError,
            httpx.HTTPError,
            ValueError,
            KeyError,
            wave.Error,
            EOFError,
        ) as exc:
            raise provider_error(exc) from None
