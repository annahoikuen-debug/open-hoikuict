"""起動スモークテスト: 本物の main.app の lifespan まで実行して起動可否を検証する。

背景: 2026-11-24 に `main.py` 内の未定義名 (logger) により lifespan が失敗し、
pytest は全緑のままアプリが起動できない状態が発生した。モジュール import だけでは
検出できないため、TestClient の context manager (lifespan 実行) まで含めて確認する。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def smoke_client(monkeypatch, tmp_path):
    monkeypatch.setenv("HOIKUICT_ENV", "development")
    monkeypatch.setenv("HOIKUICT_STAFF_AUTH_MODE", "mock")
    monkeypatch.setenv("HOIKUICT_PARENT_AUTH_MODE", "mock")
    monkeypatch.setenv("HOIKUICT_ENABLE_MOCK_AUTH", "1")
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "0")
    monkeypatch.setenv("HOIKUICT_COOKIE_SECURE", "0")
    monkeypatch.setenv("HOIKUICT_KIOSK_ACCESS_MODE", "disabled")
    monkeypatch.setenv("HOIKUICT_DATABASE_URL", (tmp_path / "smoke.db").as_posix())
    # 背景ループ (プレビュー掃除・Push配信・メール・ソルバーワーカー) を抑止
    monkeypatch.setenv("HOIKUICT_RESTORE_PROBE", "1")
    import main

    with TestClient(main.app) as client:
        yield client


def test_app_boots_and_serves_entry_page(smoke_client):
    resp = smoke_client.get("/")
    assert resp.status_code == 200
    assert "ログイン" in resp.text
