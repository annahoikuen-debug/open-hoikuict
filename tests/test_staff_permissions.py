from __future__ import annotations

from staff_permissions import (
    PERMISSION_GUIDANCE,
    STAFF_PERMISSION_DEFINITIONS,
    get_permission_guidance,
)


def test_permission_guidance_contains_all_core_keys():
    for definition in STAFF_PERMISSION_DEFINITIONS:
        assert definition.key in PERMISSION_GUIDANCE
        guidance = get_permission_guidance(definition.key)
        assert guidance["title"]
        assert guidance["description"]
        assert guidance["contact"]


def test_permission_guidance_fallback_for_unknown_key():
    guidance = get_permission_guidance("unknown_permission_abc")
    assert "アクセス権限が不足しています" in guidance["title"]
    assert "施設管理者へお問い合わせください" in guidance["contact"]
