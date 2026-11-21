"""Runtime system profile configuration for open-hoikuict.

All-in-One (Embedded) モードと 分散 SaaS (Cloud) モードを透過的に統合し、
小規模・ローカル・単一施設での外部依存ゼロ稼働と、
50園規模での分散オートスケール稼働を環境変数1つで切り替える機能を提供します。
"""

from __future__ import annotations

import enum
import logging
import os
from typing import Any, Dict

logger = logging.getLogger("hoikuict.profile")


class ProfileMode(str, enum.Enum):
    """動作プロファイルの定義。"""

    EMBEDDED = "embedded"  # 単一プロセス・外部依存ゼロ (SQLite / In-Memory Queue / Local Solver)
    CLOUD = "cloud"  # 分散 SaaS (Database-per-Tenant / Redis / Serverless Solver)


def get_active_profile() -> ProfileMode:
    """現在の有効なプロファイルを取得する。既定値は EMBEDDED。"""
    raw = os.getenv("HOIKUICT_PROFILE", "").strip().lower()
    if raw in ("cloud", "distributed", "saas", "production_cloud"):
        return ProfileMode.CLOUD
    return ProfileMode.EMBEDDED


def is_embedded_profile() -> bool:
    """組み込み All-in-One プロファイルか判定する。"""
    return get_active_profile() == ProfileMode.EMBEDDED


def is_cloud_profile() -> bool:
    """クラウド分散プロファイルか判定する。"""
    return get_active_profile() == ProfileMode.CLOUD


def should_use_redis() -> bool:
    """Redis キューを使用すべきかを判定する。

    個別設定 `HOIKUICT_USE_REDIS` があれば最優先。
    未指定時は embedded なら False (インメモリ)、cloud なら True。
    """
    raw = os.getenv("HOIKUICT_USE_REDIS")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "enabled")
    return is_cloud_profile()


def should_use_serverless_solver() -> bool:
    """Serverless Solver API を使用すべきかを判定する。

    個別設定 `HOIKUICT_USE_SERVERLESS_SOLVER` があれば最優先。
    未指定時は embedded なら False (ローカル内包ソルバー)、
    cloud なら HOIKUICT_SERVERLESS_SOLVER_URL が設定されていれば True。
    """
    raw = os.getenv("HOIKUICT_USE_SERVERLESS_SOLVER")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "enabled")
    if is_embedded_profile():
        return False
    return bool(os.getenv("HOIKUICT_SERVERLESS_SOLVER_URL", "").strip())


def should_enable_multi_tenant() -> bool:
    """Database-per-Tenant（園ごと独立DB）を有効化すべきかを判定する。

    個別設定 `HOIKUICT_TENANT_DB_MODE` があれば最優先。
    未指定時は embedded なら False (単一DB)、cloud なら True。
    """
    raw = os.getenv("HOIKUICT_TENANT_DB_MODE")
    if raw is not None:
        return raw.strip().lower() in ("multi", "1", "true", "yes", "enabled")
    return is_cloud_profile()


def get_profile_summary() -> Dict[str, Any]:
    """現在のプロファイルと主要サブシステムの状態サマリを取得する。"""
    profile = get_active_profile()
    use_redis = should_use_redis()
    use_serverless = should_use_serverless_solver()
    multi_tenant = should_enable_multi_tenant()

    return {
        "profile": profile.value,
        "database_mode": "multi_tenant (database-per-tenant)" if multi_tenant else "single (global database)",
        "task_queue": "redis (distributed)" if use_redis else "in_memory (thread pool)",
        "shift_solver": "serverless (remote container)" if use_serverless else "in_process (local HiGHS/CBC)",
    }


def format_profile_banner() -> str:
    """起動時にコンソールへ出力する整形済みプロファイルバナー文字列を返す。"""
    summary = get_profile_summary()
    prof_upper = summary["profile"].upper()

    if prof_upper == "EMBEDDED":
        mode_desc = "EMBEDDED (All-in-One Mode / Zero-External-Dependency)"
        note = "Optimized for single facility, on-premise, and local development."
    else:
        mode_desc = "CLOUD (Distributed Multi-Tenant SaaS Mode)"
        note = "Optimized for 50+ facilities with KEDA autoscaling and tenant isolation."

    lines = [
        "==================================================================",
        f"  [Nusoft / open-hoikuict] Profile: {mode_desc}",
        "------------------------------------------------------------------",
        f"  * Database     : {summary['database_mode']}",
        f"  * Task Queue   : {summary['task_queue']}",
        f"  * Shift Solver : {summary['shift_solver']}",
        f"  * Description  : {note}",
        "==================================================================",
    ]
    return "\n".join(lines)
