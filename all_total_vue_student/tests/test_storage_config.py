from pathlib import Path

import pytest

from kharakteres import config


@pytest.mark.parametrize("value", ["/absolute/path", "/absolute/path/kharakteres.sqlite"])
def test_example_path_has_actionable_error(monkeypatch, value):
    monkeypatch.setenv("SPELL_DB_PATH", value)
    with pytest.raises(ValueError, match="안내용 예시 경로"):
        config.prepare_spell_storage()


@pytest.mark.parametrize("value", ["", "data/kharakteres.sqlite"])
def test_default_and_relative_path_ignore_working_directory(monkeypatch, tmp_path, value):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("SPELL_DB_PATH", value)
    monkeypatch.chdir(tmp_path.parent)
    path = config.prepare_spell_storage()
    assert path == tmp_path / "data/kharakteres.sqlite"
    assert path.parent.is_dir()
    assert not path.exists()  # Preflight does not create a DB.
    assert list(path.parent.iterdir()) == []


def test_existing_file_is_not_modified(monkeypatch, tmp_path):
    path = tmp_path / "existing.sqlite"
    path.write_bytes(b"existing data")
    monkeypatch.setenv("SPELL_DB_PATH", str(path))
    assert config.prepare_spell_storage() == path
    assert path.read_bytes() == b"existing data"


def test_directory_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("SPELL_DB_PATH", str(tmp_path))
    with pytest.raises(ValueError, match="DB 파일 대신 폴더"):
        config.prepare_spell_storage()


def test_readonly_error_is_explained(monkeypatch, tmp_path):
    monkeypatch.setenv("SPELL_DB_PATH", str(tmp_path / "db.sqlite"))

    def readonly(*args, **kwargs):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(Path, "mkdir", readonly)
    with pytest.raises(ValueError, match="쓰기 가능한 파일 경로"):
        config.prepare_spell_storage()
