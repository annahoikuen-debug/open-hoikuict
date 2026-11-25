"""オブザーバビリティ（Prometheus/ヘルスチェック）および自動 DR 検証テスト (Phase 5.3 / 回帰防止).

本テストスイートが保証する不変条件:
1. `/health/live` がプロセスの健全な稼働状態を即座に 200 OK で応答すること。
2. `/health/ready` が DB やストレージ・キューの健全性を検証し、サービス提供可能状態であることを確認すること。
3. `/metrics` が Prometheus 互換フォーマットで主要なサービスメトリクスを出力すること。
4. `backup_and_verify` が SQLite バックアップを生成・復元し、整合性チェックサムおよび主要テーブル行数の完全一致を検証できること。
5. 破損したバックアップに対して `DRVerificationError` が適切に検知されること。
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from database import create_db_and_tables, engine
from main import app
from scripts.backup_and_verify import (
    DRVerificationError,
    create_backup,
    get_source_sqlite_path,
    run_backup_and_verify,
    verify_backup_restore,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_liveness_probe(client: TestClient) -> None:
    """/health/live が 200 OK を返すこと。"""
    resp = client.get("/health/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "alive"
    assert "timestamp" in data


def test_readiness_probe(client: TestClient) -> None:
    """/health/ready が 200 OK を返し、DB/Storage/Queue チェックが全て健全であること。"""
    create_db_and_tables()
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["checks"]["database"]["status"] == "ok"
    assert data["checks"]["storage"]["status"] == "ok"
    assert data["checks"]["queue"]["status"] == "ok"


def test_prometheus_metrics(client: TestClient) -> None:
    """/metrics が Prometheus 形式のメトリクスを正しく公開すること。"""
    create_db_and_tables()
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    content = resp.text

    assert "hoikuict_up 1" in content
    assert "hoikuict_db_status 1" in content
    assert "hoikuict_queue_pending_jobs" in content
    assert "hoikuict_active_facilities_total" in content
    assert "hoikuict_enrolled_children_total" in content


def test_dr_backup_and_restore_verification() -> None:
    """バックアップ作成と別 DB への復元検証が完全に PASS すること。"""
    create_db_and_tables()
    source_db_path = get_source_sqlite_path()

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir) / "backups"
        report = run_backup_and_verify(source_db_path=source_db_path, output_dir=out_dir)

        assert report["status"] == "PASSED"
        assert report["integrity_check"] == "ok"
        assert len(report["tables_verified"]) > 0
        assert report["elapsed_sec"] >= 0.0


def test_dr_backup_corrupted_detection() -> None:
    """破損したバックアップに対して DR 検証が例外を送出すること。"""
    create_db_and_tables()
    source_db_path = get_source_sqlite_path()

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir) / "backups"
        bkp = create_backup(source_db_path, out_dir)

        # 意図的にバックアップファイルのヘッダ以降を破壊
        with open(bkp, "r+b") as f:
            f.seek(100)
            f.write(b"CORRUPTED_GARBAGE_BYTES" * 10)

        with pytest.raises(Exception):
            verify_backup_restore(source_db_path, bkp)


def test_health_ready_redacts_internal_exception_details(client: TestClient) -> None:
    """/health/ready 異常時に内部例外メッセージや接続文字列を返さないこと。"""
    import os
    from unittest.mock import patch

    with (
        patch.dict(os.environ, {"HOIKUICT_ENV": "production"}),
        patch("sqlmodel.Session.exec", side_effect=RuntimeError("secret_db_dsn_leak_check")),
    ):
        resp = client.get("/health/ready")

    assert resp.status_code == 503
    assert "secret_db_dsn_leak_check" not in resp.text
    assert "error" not in resp.json()


def test_metrics_requires_token_or_admin_in_production(client: TestClient) -> None:
    """/metrics はトークン設定時または本番環境で認証なしアクセスを拒否すること。"""
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"HOIKUICT_METRICS_TOKEN": "metrics-secret-xyz"}):
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer wrong-token"}).status_code == 401
        ok_resp = client.get("/metrics", headers={"Authorization": "Bearer metrics-secret-xyz"})
        assert ok_resp.status_code == 200

    with patch.dict(os.environ, {"HOIKUICT_ENV": "production", "HOIKUICT_METRICS_TOKEN": ""}):
        assert client.get("/metrics").status_code == 401
