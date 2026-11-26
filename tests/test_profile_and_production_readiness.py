"""Tests for runtime profile switching (EMBEDDED / CLOUD) and production security readiness."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest

import profile_config
import security_config


def test_profile_defaults_to_embedded(monkeypatch):
    for key in (
        "HOIKUICT_PROFILE",
        "HOIKUICT_USE_REDIS",
        "HOIKUICT_USE_SERVERLESS_SOLVER",
        "HOIKUICT_SERVERLESS_SOLVER_URL",
        "HOIKUICT_TENANT_DB_MODE",
    ):
        monkeypatch.delenv(key, raising=False)

    assert profile_config.get_active_profile() == profile_config.ProfileMode.EMBEDDED
    assert profile_config.is_embedded_profile() is True
    assert profile_config.is_cloud_profile() is False
    summary = profile_config.get_profile_summary()
    assert summary["profile"] == "embedded"
    assert "single" in summary["database_mode"]
    assert "in_memory" in summary["task_queue"]
    assert "in_process" in summary["shift_solver"]


def test_profile_cloud_enables_distributed_subsystems(monkeypatch):
    monkeypatch.setenv("HOIKUICT_PROFILE", "cloud")
    monkeypatch.delenv("HOIKUICT_USE_REDIS", raising=False)
    monkeypatch.delenv("HOIKUICT_TENANT_DB_MODE", raising=False)
    monkeypatch.delenv("HOIKUICT_USE_SERVERLESS_SOLVER", raising=False)
    monkeypatch.setenv("HOIKUICT_SERVERLESS_SOLVER_URL", "https://solver.example.internal")

    assert profile_config.get_active_profile() == profile_config.ProfileMode.CLOUD
    assert profile_config.should_use_redis() is True
    assert profile_config.should_enable_multi_tenant() is True
    assert profile_config.should_use_serverless_solver() is True

    # Individual override takes precedence over profile default
    monkeypatch.setenv("HOIKUICT_USE_REDIS", "0")
    assert profile_config.should_use_redis() is False


def _load_production_example_env(monkeypatch) -> None:
    for var in (
        "HOIKUICT_ENABLE_MOCK_AUTH",
        "HOIKUICT_ENABLE_MOCK_ROLE_OVERRIDE",
        "HOIKUICT_KIOSK_TOKEN",
        "HOIKUICT_ALLOW_MULTIWORKER_RATE_LIMIT",
        "HOIKUICT_PUSH_VAPID_PUBLIC_KEY",
        "HOIKUICT_PUSH_VAPID_PRIVATE_KEY",
        "HOIKUICT_PUSH_VAPID_SUBJECT",
    ):
        monkeypatch.delenv(var, raising=False)
    env_file = Path(__file__).resolve().parent.parent / ".env.production.example"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if "replace-with" in v:
            v = secrets.token_urlsafe(32)
        monkeypatch.setenv(k, v)


def test_production_example_passes_runtime_security_validation(monkeypatch):
    _load_production_example_env(monkeypatch)
    security_config.validate_runtime_security()


def test_production_rejects_mock_auth_and_open_kiosk(monkeypatch):
    _load_production_example_env(monkeypatch)
    monkeypatch.setenv("HOIKUICT_ENABLE_MOCK_AUTH", "1")
    with pytest.raises(RuntimeError):
        security_config.validate_runtime_security()

    _load_production_example_env(monkeypatch)
    monkeypatch.setenv("HOIKUICT_KIOSK_ACCESS_MODE", "open")
    with pytest.raises(RuntimeError):
        security_config.validate_runtime_security()
