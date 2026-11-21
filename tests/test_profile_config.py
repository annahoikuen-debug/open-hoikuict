"""Tests for profile_config and runtime system profile switching."""

from __future__ import annotations

import os
from unittest import mock

from profile_config import (
    ProfileMode,
    format_profile_banner,
    get_active_profile,
    get_profile_summary,
    is_cloud_profile,
    is_embedded_profile,
    should_enable_multi_tenant,
    should_use_redis,
    should_use_serverless_solver,
)


def test_default_profile_is_embedded():
    """環境変数未指定時の既定値は EMBEDDED で、外部依存ゼロ構成になること。"""
    with mock.patch.dict(os.environ, {}, clear=True):
        assert get_active_profile() == ProfileMode.EMBEDDED
        assert is_embedded_profile() is True
        assert is_cloud_profile() is False
        assert should_use_redis() is False
        assert should_use_serverless_solver() is False
        assert should_enable_multi_tenant() is False


def test_cloud_profile():
    """HOIKUICT_PROFILE=cloud 指定時に分散 SaaS 構成が有効化されること。"""
    env = {
        "HOIKUICT_PROFILE": "cloud",
        "HOIKUICT_SERVERLESS_SOLVER_URL": "https://solver.example.com",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        assert get_active_profile() == ProfileMode.CLOUD
        assert is_embedded_profile() is False
        assert is_cloud_profile() is True
        assert should_use_redis() is True
        assert should_use_serverless_solver() is True
        assert should_enable_multi_tenant() is True


def test_individual_env_override():
    """個別の環境変数が指定された場合、プロファイルの既定値より個別設定が優先されること。"""
    # embedded なのに明示的に Redis を使いたい場合
    env_embedded = {
        "HOIKUICT_PROFILE": "embedded",
        "HOIKUICT_USE_REDIS": "1",
        "HOIKUICT_TENANT_DB_MODE": "multi",
    }
    with mock.patch.dict(os.environ, env_embedded, clear=True):
        assert is_embedded_profile() is True
        assert should_use_redis() is True
        assert should_enable_multi_tenant() is True

    # cloud なのに Redis を切りたい場合
    env_cloud = {
        "HOIKUICT_PROFILE": "cloud",
        "HOIKUICT_USE_REDIS": "0",
        "HOIKUICT_TENANT_DB_MODE": "single",
    }
    with mock.patch.dict(os.environ, env_cloud, clear=True):
        assert is_cloud_profile() is True
        assert should_use_redis() is False
        assert should_enable_multi_tenant() is False


def test_summary_and_banner_format():
    """サマリ取得およびバナー出力が例外なく正しく生成されること。"""
    with mock.patch.dict(os.environ, {"HOIKUICT_PROFILE": "embedded"}, clear=True):
        summary = get_profile_summary()
        assert summary["profile"] == "embedded"
        assert "single" in summary["database_mode"]
        assert "in_memory" in summary["task_queue"]
        assert "in_process" in summary["shift_solver"]

        banner = format_profile_banner()
        assert "EMBEDDED" in banner
        assert "Zero-External-Dependency" in banner

    with mock.patch.dict(os.environ, {"HOIKUICT_PROFILE": "cloud"}, clear=True):
        summary = get_profile_summary()
        assert summary["profile"] == "cloud"
        assert "multi_tenant" in summary["database_mode"]
        assert "redis" in summary["task_queue"]

        banner = format_profile_banner()
        assert "CLOUD" in banner


def test_tasks_queue_integration_with_profile():
    """tasks.queue が profile_config と連携し、embedded 時に安全にインメモリへ倒れること。"""
    from tasks.queue import is_redis_available

    with mock.patch.dict(os.environ, {"HOIKUICT_PROFILE": "embedded"}, clear=True):
        # Redisの接続チェックを行わずに即時 False を返すこと
        assert is_redis_available(force_check=True) is False


def test_serverless_client_integration_with_profile():
    """serverless_client が profile_config と連携し、embedded 時にローカルソルバーへ倒れること。"""
    from shift_schedule.services.serverless_client import is_serverless_configured

    env = {
        "HOIKUICT_PROFILE": "embedded",
        # URLが指定されていても embedded ではローカル優先
        "HOIKUICT_SERVERLESS_SOLVER_URL": "https://solver.example.com",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        assert is_serverless_configured() is False

    # cloud なら URL があれば True
    with mock.patch.dict(os.environ, {"HOIKUICT_PROFILE": "cloud", "HOIKUICT_SERVERLESS_SOLVER_URL": "https://solver.example.com"}, clear=True):
        assert is_serverless_configured() is True
