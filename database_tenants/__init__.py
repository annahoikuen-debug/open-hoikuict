"""Database-per-Tenant package for OpenHoikuICT.

50園の同時利用において、ロック競合ゼロ・障害波及ゼロ・超高速なI/Oを実現する
独立DBアーキテクチャのコアモジュール群。
"""

from database_tenants.dispatcher import (
    get_master_session,
    get_session_for_facility,
    get_tenant_session,
    is_multi_tenant_enabled,
    master_engine,
    tenant_engine_registry,
)
from database_tenants.migration import (
    ensure_tenant_template_initialized,
    migrate_all_tenants_parallel,
    migrate_single_tenant_db,
    provision_tenant_from_template,
)
from database_tenants.registry import TenantEngineRegistry

__all__ = [
    "TenantEngineRegistry",
    "tenant_engine_registry",
    "master_engine",
    "get_tenant_session",
    "get_master_session",
    "get_session_for_facility",
    "is_multi_tenant_enabled",
    "ensure_tenant_template_initialized",
    "provision_tenant_from_template",
    "migrate_single_tenant_db",
    "migrate_all_tenants_parallel",
]
