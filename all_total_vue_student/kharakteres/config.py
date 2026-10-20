"""Shared storage configuration for launcher and direct server startup."""

import os
from pathlib import Path
from tempfile import TemporaryFile

ROOT = Path(__file__).resolve().parents[1]


def spell_db_path():
    value = os.getenv("SPELL_DB_PATH", "").strip()
    if value == "/absolute/path" or value.startswith("/absolute/path/"):
        raise ValueError(
            "SPELL_DB_PATH에 안내용 예시 경로 /absolute/path가 설정되어 있습니다. "
            ".env에서 SPELL_DB_PATH 줄을 삭제하거나 "
            "SPELL_DB_PATH=data/kharakteres.sqlite로 수정하세요."
        )
    path = Path(value).expanduser() if value else ROOT / "data/kharakteres.sqlite"
    return path if path.is_absolute() else ROOT / path


def prepare_spell_storage():
    path = spell_db_path()
    try:
        if path.is_dir():
            raise IsADirectoryError("DB 파일 대신 폴더가 지정되었습니다")
        path.parent.mkdir(parents=True, exist_ok=True)
        # SQLite also needs directory access for WAL/SHM sidecars.
        with TemporaryFile(dir=path.parent):
            pass
        if path.exists():
            # Never truncate or change existing records during preflight.
            with path.open("r+b"):
                pass
    except OSError as exc:
        raise ValueError(
            f"주문 DB 경로를 사용할 수 없습니다: {path} ({exc.strerror or str(exc)}). "
            ".env의 SPELL_DB_PATH를 쓰기 가능한 파일 경로로 수정하세요. "
            "기본값: data/kharakteres.sqlite"
        ) from exc
    return path
