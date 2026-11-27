from __future__ import annotations

import asyncio
from contextlib import contextmanager
import logging
import os
import random
import threading
import time
from datetime import date, timedelta

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlmodel import SQLModel, Session, create_engine, select

from family_support import bootstrap_family_data, sync_parent_child_links, sync_family_to_children
from time_utils import local_today, utc_now
import family_archive_guard  # noqa: F401 -- requires audited archive-state transitions

DATABASE_URL = os.getenv("HOIKUICT_DATABASE_URL", "sqlite:///./hoikuict.db")
# Heroku / Supabase / Render 等の postgres:// を postgresql:// に正規化
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

_database_url = make_url(DATABASE_URL)
_backend = _database_url.get_backend_name()
_is_sqlite_url = _backend == "sqlite"
_is_postgres_url = _backend in ("postgresql", "postgres")

if _is_sqlite_url:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"timeout": 30},
    )
elif _is_postgres_url:
    from sqlalchemy.pool import QueuePool

    engine = create_engine(
        DATABASE_URL,
        echo=False,
        poolclass=QueuePool,
        pool_size=int(os.getenv("HOIKUICT_DB_POOL_SIZE", "20")),
        max_overflow=int(os.getenv("HOIKUICT_DB_MAX_OVERFLOW", "10")),
        pool_timeout=int(os.getenv("HOIKUICT_DB_POOL_TIMEOUT", "30")),
        pool_recycle=int(os.getenv("HOIKUICT_DB_POOL_RECYCLE", "1800")),
        pool_pre_ping=True,  # 切断されたコネクションの自動検知と再接続
    )
else:
    engine = create_engine(DATABASE_URL, echo=False)

logger = logging.getLogger(__name__)


if _is_sqlite_url:
    @event.listens_for(engine, "connect")
    def _set_sqlite_connection_pragmas(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA cache_size = -64000")
            cursor.execute("PRAGMA temp_store = MEMORY")
            cursor.execute("PRAGMA wal_autocheckpoint=1000")
            cursor.execute("PRAGMA journal_size_limit=67108864")
            cursor.execute("PRAGMA mmap_size=268435456")
        finally:
            cursor.close()
elif _is_postgres_url:
    @event.listens_for(engine, "connect")
    def _set_postgres_connection_settings(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET timezone = 'Asia/Tokyo'")
            cursor.execute("SET application_name = 'open-hoikuict'")
        except Exception as exc:
            logger.warning("PostgreSQL セッション設定に失敗しました: %s", exc)
        finally:
            cursor.close()

DEFAULT_CLASSROOMS = [
    ("ひよこ組", 1),
    ("うさぎ組", 2),
    ("きりん組", 3),
]

def get_session():
    """DBセッションプロバイダ。

    HOIKUICT_TENANT_DB_MODE=multi（または enabled/1/true）の場合、
    各園の物理独立DB（storage/tenants/{facility_id}.db）へ透過的にルーティングする。
    未設定・単一DBモード時は従来のグローバル engine セッションを提供する。
    """
    try:
        from profile_config import should_enable_multi_tenant

        use_multi = should_enable_multi_tenant()
    except ImportError:
        mode = os.getenv("HOIKUICT_TENANT_DB_MODE", "").lower()
        use_multi = mode in ("multi", "1", "true", "enabled")

    if use_multi:
        from database_tenants.dispatcher import get_tenant_session

        yield from get_tenant_session()
        return

    with Session(engine) as session:
        yield session


async def run_db_async(func, *args, **kwargs):
    """非同期コンテキストから同期 DB 操作をスレッドプールで実行する。

    SQLModel/SQLAlchemy の同期 Session はブロッキング I/O を含むため、
    FastAPI イベントループをブロックしないよう asyncio.to_thread でオフロードする。
    """
    return await asyncio.to_thread(func, *args, **kwargs)


_sqlite_write_lock = threading.RLock()


@contextmanager
def sqlite_write_section():
    """組み込み SQLite 構成で同時書き込みを直列化し、SQLITE_BUSY 待機遅延を抑止する。"""
    if not _is_sqlite_url:
        yield
        return
    with _sqlite_write_lock:
        yield


def commit_with_retry(session: Session, *, max_attempts: int = 5) -> None:
    """SQLite の書き込み競合時にジッター付き指数バックオフで commit を再試行する。"""
    if not _is_sqlite_url:
        session.commit()
        return
    with sqlite_write_section():
        for attempt in range(max_attempts):
            try:
                session.commit()
                return
            except OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == max_attempts - 1:
                    raise
                time.sleep(0.02 * (2**attempt) + random.uniform(0.0, 0.015))


def sqlite_wal_checkpoint(mode: str = "PASSIVE") -> None:
    """SQLite WAL の肥大化を抑えるためチェックポイントを実行する。"""
    if not _is_sqlite_url:
        return
    database_name = engine.url.database
    if not database_name or database_name == ":memory:":
        return
    safe_mode = mode if mode in {"PASSIVE", "FULL", "RESTART", "TRUNCATE"} else "PASSIVE"
    try:
        with engine.connect() as conn:
            conn.execute(text(f"PRAGMA wal_checkpoint({safe_mode})"))
    except Exception as exc:
        logger.debug("SQLite WAL checkpoint スキップ: %s", exc)


# 組み込みマイグレーションの実行順序。適用済みのものは schema_migrations
# テーブルに記録され、再実行時はスキップされる。新しいマイグレーションは
# このリストの末尾に追記すること(既存エントリの順序は変更しない)。
# 関数参照を含むため、モジュール読み込み後に create_db_and_tables() 内で構築する。
from db_migrations.sqlite_legacy import (  # noqa: F401
    _sqlite_migrations,
    _migrate_facility_settings,
    _migrate_paid_leave_tables,
    _migrate_medication_administrations,
    _migrate_observation_sharing_columns,
    _migrate_spec_20260924_columns,
    _migrate_family_archive,
    _migrate_add_child_columns,
    _migrate_add_child_health_profile_columns,
    _migrate_add_attendance_columns,
    _migrate_guardian_confirmation_columns,
    _migrate_pickup_history_columns,
    _migrate_add_daily_contact_columns,
    _migrate_add_parent_account_columns,
    _migrate_add_guardian_columns,
    _migrate_parent_mail_delivery_columns,
    _migrate_add_family_columns,
    _migrate_data_transfer_audit,
    _migrate_add_message_columns,
    _migrate_add_meeting_note_columns,
    _migrate_notice_columns,
    _migrate_document_review_columns,
    _migrate_add_calendar_columns,
    _migrate_survey_tables,
    _migrate_weekly_sheet_columns,
    _migrate_monthly_sheet_columns,
    _migrate_annual_sheet_columns,
    _migrate_plan_document_child_record_columns,
    _migrate_plan_document_action_columns,
    _migrate_plan_review_notification_columns,
    _migrate_parent_push_delivery_columns,
    _migrate_parent_push_preference_extra_mute_columns,
    _migrate_attendance_idempotency_key,
    _migrate_attendance_lock_version,
    _migrate_message_templates_table,
    _migrate_billing_fee_labels,
    _migrate_zengin_workflow,
    _migrate_family_bootstrap,
    _migrate_sync_health_records_from_legacy,
    _migrate_extended_care_billing_transfer,
    _migrate_care_certification_and_extended_care_columns,
    _migrate_shift_schedule_tables,
    _migrate_shift_timefold_enhancements,
    _migrate_document_export_permissions,
    _migrate_document_export_history,
    _migrate_pims_attendance_tables,
    _migrate_parent_medical_table,
    _migrate_daily_contact_review_columns,
    _migrate_smart_hud_simple_mode_and_nap_checks,
)


def _ensure_schema_migrations_table() -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "migration_id VARCHAR(128) PRIMARY KEY, "
            "applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )


def _applied_migrations() -> set[str]:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT migration_id FROM schema_migrations")
        return {row[0] for row in rows}


def _record_migration(conn, migration_id: str) -> None:
    conn.exec_driver_sql(
        "INSERT INTO schema_migrations (migration_id) VALUES (?)",
        (migration_id,),
    )


def run_alembic_migrations() -> None:
    """Alembic をプログラム経由で実行し、データベースを最新リビジョン (head) に更新する。"""
    from alembic import command
    from alembic.config import Config

    alembic_ini_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alembic.ini")
    if not os.path.exists(alembic_ini_path):
        logger.warning("alembic.ini が見つからないため、Alembic マイグレーションをスキップします: %s", alembic_ini_path)
        return
    alembic_cfg = Config(alembic_ini_path)
    logger.info("Alembic マイグレーション (upgrade head) を実行します...")
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic マイグレーションが完了しました。")


_SCHEMA_INIT_LOCK = threading.Lock()


def create_db_and_tables() -> None:
    with _SCHEMA_INIT_LOCK:
        _create_db_and_tables_unlocked()


def _create_db_and_tables_unlocked() -> None:
    import models  # noqa: F401
    import child_records.models  # noqa: F401
    import plan_docs.db_models  # noqa: F401
    import shift_schedule.db_models  # noqa: F401

    if engine.dialect.name != "sqlite":
        if os.getenv("HOIKUICT_AUTO_MIGRATE") == "1":
            run_alembic_migrations()
            return
        if os.getenv("HOIKUICT_ALLOW_UNMANAGED_SCHEMA") != "1":
            raise RuntimeError(
                "組み込みマイグレーションはSQLite専用です。"
                "他DBではHOIKUICT_AUTO_MIGRATE=1（Alembic自動適用）または"
                "HOIKUICT_ALLOW_UNMANAGED_SCHEMA=1と外部管理済みスキーマが必要です。"
            )
        _validate_unmanaged_schema()
        return

    _enable_sqlite_wal()
    SQLModel.metadata.create_all(engine)
    _ensure_schema_migrations_table()
    applied = _applied_migrations()
    for migration_id, migrate in _sqlite_migrations():
        if migration_id in applied:
            continue
        logger.info("applying migration %s", migration_id)
        migrate()
        with engine.begin() as conn:
            _record_migration(conn, migration_id)
    _ensure_default_organization_and_facility()
    _validate_sqlite_foreign_keys()


def _ensure_default_organization_and_facility() -> None:
    """デフォルト法人および施設レコードが存在しない場合、シームレスに初期投入する。"""
    from sqlmodel import Session
    from models.organization import (
        DEFAULT_FACILITY_ID,
        DEFAULT_ORGANIZATION_ID,
        Facility,
        Organization,
        get_default_facility,
        get_default_organization,
    )

    try:
        with Session(engine) as session:
            org = session.get(Organization, DEFAULT_ORGANIZATION_ID)
            if org is None:
                session.add(get_default_organization())
                session.commit()
            fac = session.get(Facility, DEFAULT_FACILITY_ID)
            if fac is None:
                session.add(get_default_facility())
                session.commit()
    except Exception as exc:
        logger.debug("デフォルト法人・施設初期化スキップ: %s", exc)


def _enable_sqlite_wal() -> None:
    database_name = engine.url.database
    if not database_name or database_name == ":memory:":
        return
    with engine.connect() as conn:
        mode = str(conn.execute(text("PRAGMA journal_mode=WAL")).scalar_one()).lower()
    if mode != "wal":
        raise RuntimeError(f"SQLite WALを有効化できませんでした: journal_mode={mode}")


def _validate_sqlite_foreign_keys() -> None:
    with engine.connect() as conn:
        violations = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
    if violations:
        sample = ", ".join(str(tuple(row)) for row in violations[:5])
        raise RuntimeError(f"SQLite外部キー違反があります: {sample}")


def _validate_unmanaged_schema() -> None:
    db_inspector = inspect(engine)
    existing_tables = set(db_inspector.get_table_names())
    missing_tables = sorted(set(SQLModel.metadata.tables) - existing_tables)
    missing_columns: list[str] = []
    for table_name, table in SQLModel.metadata.tables.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {item["name"] for item in db_inspector.get_columns(table_name)}
        for column_name in table.columns.keys():
            if column_name not in existing_columns:
                missing_columns.append(f"{table_name}.{column_name}")
    if missing_tables or missing_columns:
        raise RuntimeError(
            "外部管理スキーマが不足しています: "
            f"tables={missing_tables[:10]}, columns={missing_columns[:20]}"
        )


def _table_columns(table_name: str) -> list[str]:
    with engine.connect() as conn:
        result = conn.execute(text(f"PRAGMA table_info({table_name})"))
        return [row[1] for row in result]


def _log_migration_skip(migration_name: str, exc: Exception) -> None:
    raise RuntimeError(f"{migration_name} migration failed") from exc


def seed_classroom_data() -> None:
    from models import Classroom

    with Session(engine) as session:
        classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
        if classrooms:
            return

        for name, order in DEFAULT_CLASSROOMS:
            session.add(Classroom(name=name, display_order=order))

        session.commit()


def seed_extended_care_fee_rules() -> None:
    from models import ExtendedCareFeeRule

    with Session(engine) as session:
        if session.exec(select(ExtendedCareFeeRule)).first():
            return

        session.add(
            ExtendedCareFeeRule(
                name="標準延長保育料",
                effective_from=date(2020, 1, 1),
                start_time="18:00",
                grace_minutes=5,
                rounding_minutes=15,
                unit_price=100,
                daily_cap_amount=None,
                is_active=True,
            )
        )
        session.commit()


def seed_sample_data() -> None:
    from models import Child, ChildStatus, Classroom, Family, Guardian

    with Session(engine) as session:
        if session.exec(select(Child)).first():
            return

        classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
        classroom_ids = [classroom.id for classroom in classrooms if classroom.id is not None]

        def classroom_id_at(index: int) -> int | None:
            if not classroom_ids:
                return None
            return classroom_ids[min(index, len(classroom_ids) - 1)]

        tanaka_family = Family(
            family_name="田中家",
            home_address="東京都渋谷区1-2-3",
            home_phone="03-1234-5678",
            shared_profile={
                "guardians": [
                    {
                        "order": 1,
                        "last_name": "田中",
                        "first_name": "真由美",
                        "last_name_kana": "タナカ",
                        "first_name_kana": "マユミ",
                        "relationship": "母",
                        "phone": "090-1111-2222",
                        "workplace": "サンプル商事",
                        "workplace_address": "東京都港区1-1-1",
                        "workplace_phone": "03-1111-2222",
                    },
                    {
                        "order": 2,
                        "last_name": "田中",
                        "first_name": "健一",
                        "last_name_kana": "タナカ",
                        "first_name_kana": "ケンイチ",
                        "relationship": "父",
                        "phone": "090-3333-4444",
                        "workplace": "サンプル工業",
                        "workplace_address": "東京都品川区2-2-2",
                        "workplace_phone": "03-3333-4444",
                    },
                ]
            },
        )
        sato_family = Family(
            family_name="佐藤家",
            home_address="東京都新宿区4-5-6",
            home_phone="03-2345-6789",
            shared_profile={
                "guardians": [
                    {
                        "order": 1,
                        "last_name": "佐藤",
                        "first_name": "真由美",
                        "last_name_kana": "サトウ",
                        "first_name_kana": "マユミ",
                        "relationship": "母",
                        "phone": "090-5555-6666",
                        "workplace": "グリーン企画",
                        "workplace_address": "東京都新宿区7-8-9",
                        "workplace_phone": "03-5555-6666",
                    }
                ]
            },
        )
        ito_family = Family(
            family_name="伊藤家",
            home_address="東京都目黒区9-8-7",
            home_phone="03-3456-7890",
            shared_profile={
                "guardians": [
                    {
                        "order": 1,
                        "last_name": "伊藤",
                        "first_name": "恵",
                        "last_name_kana": "イトウ",
                        "first_name_kana": "メグミ",
                        "relationship": "母",
                        "phone": "090-7777-8888",
                        "workplace": "ブルークリニック",
                        "workplace_address": "東京都目黒区3-3-3",
                        "workplace_phone": "03-7777-8888",
                    }
                ]
            },
        )
        session.add(tanaka_family)
        session.add(sato_family)
        session.add(ito_family)
        session.flush()

        children = [
            Child(
                last_name="田中",
                first_name="さくら",
                last_name_kana="タナカ",
                first_name_kana="サクラ",
                birth_date=date(2020, 4, 5),
                enrollment_date=date(2023, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom_id_at(1),
                family_id=tanaka_family.id,
                extra_data={"allergy": ["卵"], "medical_notes": "特記事項なし"},
            ),
            Child(
                last_name="田中",
                first_name="はると",
                last_name_kana="タナカ",
                first_name_kana="ハルト",
                birth_date=date(2021, 8, 12),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom_id_at(0),
                family_id=tanaka_family.id,
                extra_data={"allergy": [], "medical_notes": ""},
            ),
            Child(
                last_name="佐藤",
                first_name="真由美",
                last_name_kana="サトウ",
                first_name_kana="マユミ",
                birth_date=date(2019, 6, 15),
                enrollment_date=date(2022, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom_id_at(2),
                family_id=sato_family.id,
                extra_data={"allergy": ["乳"], "medical_notes": "エピペン持参"},
            ),
            Child(
                last_name="伊藤",
                first_name="ネオ",
                last_name_kana="イトウ",
                first_name_kana="ネオ",
                birth_date=date(2021, 4, 12),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom_id_at(0),
                family_id=ito_family.id,
                extra_data={"allergy": [], "medical_notes": ""},
            ),
            Child(
                last_name="山田",
                first_name="こうた",
                last_name_kana="ヤマダ",
                first_name_kana="コウタ",
                birth_date=date(2018, 11, 3),
                enrollment_date=date(2021, 4, 1),
                withdrawal_date=date(2025, 3, 31),
                status=ChildStatus.graduated,
                extra_data={"allergy": [], "medical_notes": ""},
            ),
        ]
        for child in children:
            session.add(child)
        session.flush()

        children[1].older_sibling_id = children[0].id
        session.add(children[1])

        for family in (tanaka_family, sato_family, ito_family):
            sync_family_to_children(session, family, updated_at=utc_now())

        session.add(
            Guardian(
                child_id=children[4].id,
                last_name="山田",
                first_name="太郎",
                relationship="父",
                phone="090-9999-0000",
                workplace="レッド建設",
                workplace_address="東京都世田谷区5-5-5",
                workplace_phone="03-9999-0000",
                order=1,
            )
        )

        session.commit()


def seed_debug_demo_data() -> dict[str, int]:
    """Create rolling operational data for local mock-auth development."""

    from demo_data_generation import seed_dynamic_demo_data

    with Session(engine) as session:
        counts = seed_dynamic_demo_data(session)
        session.commit()
        return counts


def seed_parent_portal_data() -> None:
    from models import (
        Child,
        ChildStatus,
        DailyContactEntry,
        Family,
        Notice,
        NoticePriority,
        NoticeRead,
        NoticeStatus,
        NoticeTarget,
        NoticeTargetType,
        ParentAccount,
        ParentAccountStatus,
    )

    with Session(engine) as session:
        if session.exec(select(ParentAccount)).first():
            return

        families = session.exec(
            select(Family).order_by(Family.id)
        ).all()
        if not families:
            bootstrap_family_data(session)
            session.flush()
            families = session.exec(select(Family).order_by(Family.id)).all()
        if not families:
            return

        tanaka_family = families[0]
        sato_family = families[1] if len(families) > 1 else families[0]

        accounts = [
            ParentAccount(
                display_name="田中 健一",
                email="tanaka.parent@example.com",
                phone="090-1111-0001",
                home_address=tanaka_family.home_address,
                workplace="サンプル商事",
                workplace_address="東京都港区1-1-1",
                workplace_phone="03-1111-1111",
                family_id=tanaka_family.id,
                status=ParentAccountStatus.active,
                invited_at=utc_now(),
            ),
            ParentAccount(
                display_name="佐藤 真由美",
                email="sato.parent@example.com",
                phone="090-2222-0002",
                home_address=sato_family.home_address,
                workplace="グリーン企画",
                workplace_address="東京都新宿区7-8-9",
                workplace_phone="03-2222-2222",
                family_id=sato_family.id,
                status=ParentAccountStatus.active,
                invited_at=utc_now(),
            ),
        ]
        for account in accounts:
            session.add(account)
        session.flush()

        families = session.exec(
            select(Family)
            .where(Family.id.in_([tanaka_family.id, sato_family.id]))
        ).all()
        for family in families:
            session.refresh(family)
            sync_parent_child_links(session, family)

        today = local_today()
        enrolled_children = session.exec(
            select(Child)
            .where(Child.status == ChildStatus.enrolled)
            .order_by(Child.last_name_kana, Child.first_name_kana)
        ).all()
        tanaka_child = next((child for child in enrolled_children if child.family_id == tanaka_family.id), None)
        sato_child = next((child for child in enrolled_children if child.family_id == sato_family.id), None)

        if tanaka_child:
            session.add(
                DailyContactEntry(
                    child_id=tanaka_child.id,
                    parent_account_id=accounts[0].id,
                    target_date=today,
                    temperature="36.7",
                    sleep_notes="21:00-6:30",
                    breakfast_status="完食",
                    bowel_movement_status="あり",
                    mood="元気",
                    cough="なし",
                    runny_nose="なし",
                    medication="なし",
                    condition_note="朝から元気です。",
                    contact_note="本日は16:30ごろお迎え予定です。",
                    submitted_at=utc_now(),
                )
            )
        if sato_child:
            session.add(
                DailyContactEntry(
                    child_id=sato_child.id,
                    parent_account_id=accounts[1].id,
                    target_date=today,
                    temperature="37.0",
                    sleep_notes="20:30-6:00",
                    breakfast_status="少なめ",
                    bowel_movement_status="なし",
                    mood="少し眠そう",
                    cough="少し",
                    runny_nose="なし",
                    medication="なし",
                    condition_note="少し鼻水があります。",
                    contact_note="様子を見てください。",
                    submitted_at=utc_now(),
                )
            )

        all_notice = Notice(
            title="今週の持ち物について",
            body="来週は避難訓練があります。カラー帽子と上履きを忘れずにお持ちください。",
            priority=NoticePriority.normal,
            status=NoticeStatus.published,
            publish_start_at=utc_now() - timedelta(hours=2),
            created_by="管理者サンプル",
        )
        session.add(all_notice)
        session.flush()
        session.add(NoticeTarget(notice_id=all_notice.id, target_type=NoticeTargetType.all))

        if tanaka_child and tanaka_child.classroom_id:
            classroom_notice = Notice(
                title="クラス懇談会のお知らせ",
                body="今週金曜日の16:00よりクラス懇談会を行います。ご都合をお知らせください。",
                priority=NoticePriority.high,
                status=NoticeStatus.published,
                publish_start_at=utc_now() - timedelta(hours=2),
                created_by="管理者サンプル",
            )
            session.add(classroom_notice)
            session.flush()
            session.add(
                NoticeTarget(
                    notice_id=classroom_notice.id,
                    target_type=NoticeTargetType.classroom,
                    target_value=str(tanaka_child.classroom_id),
                )
            )

        if sato_child:
            child_notice = Notice(
                title="個別連絡",
                body=f"{sato_child.full_name} さんの体調確認をお願いします。",
                priority=NoticePriority.high,
                status=NoticeStatus.published,
                publish_start_at=utc_now() - timedelta(hours=2),
                created_by="管理者サンプル",
            )
            session.add(child_notice)
            session.flush()
            session.add(
                NoticeTarget(
                    notice_id=child_notice.id,
                    target_type=NoticeTargetType.child,
                    target_value=str(sato_child.id),
                )
            )

        session.flush()
        session.add(
            NoticeRead(
                notice_id=all_notice.id,
                parent_account_id=accounts[0].id,
                read_at=utc_now(),
            )
        )
        session.commit()


def bootstrap_family_records() -> None:
    from models import Family

    with Session(engine) as session:
        # The bootstrap migrates ledgers from before families existed. Once a
        # family ledger exists, unlinked imports must be associated explicitly;
        # restarting must not create duplicates or overwrite existing contacts.
        if session.exec(select(Family.id).limit(1)).first() is not None:
            return
        bootstrap_family_data(session)
        session.commit()


def bootstrap_health_records() -> None:
    from child_health_service import sync_health_records_from_legacy_extra_data
    from models import Child

    with Session(engine) as session:
        children = session.exec(select(Child)).all()
        changed = False
        for child in children:
            changed = sync_health_records_from_legacy_extra_data(session, child) or changed
        if changed:
            session.commit()


def seed_calendar_data() -> None:
    from models import (
        Calendar,
        CalendarMember,
        CalendarMemberRole,
        CalendarType,
        CalendarUserPreference,
        USER_SOURCE_LOCAL_SAMPLE,
        USER_SOURCE_WEB_DEMO,
        User,
    )

    with Session(engine) as session:
        web_demo_users = session.exec(
            select(User).where(
                User.provisioning_source == USER_SOURCE_WEB_DEMO,
                User.is_active.is_(True),
            )
        ).all()
        if web_demo_users:
            web_demo_identities = {
                (user.display_name.strip(), user.staff_role)
                for user in web_demo_users
            }
            local_duplicates = session.exec(
                select(User).where(
                    User.provisioning_source == USER_SOURCE_LOCAL_SAMPLE,
                    User.is_active.is_(True),
                )
            ).all()
            changed = False
            for user in local_duplicates:
                if (user.display_name.strip(), user.staff_role) not in web_demo_identities:
                    continue
                user.is_active = False
                user.updated_at = utc_now()
                session.add(user)
                changed = True
            if changed:
                session.commit()
            return

        staff_specs = [
            {"email": "principal@example.com", "display_name": "園長", "staff_role": "admin", "staff_sort_order": 10, "color": "#2563EB", "can_manage_child_records": True, "can_manage_billing_accounts": False},
            {"email": "chief@example.com", "display_name": "主任", "staff_role": "admin", "staff_sort_order": 20, "color": "#7C3AED", "can_manage_child_records": True, "can_manage_billing_accounts": False},
            {"email": "nurse@example.com", "display_name": "看護師", "staff_role": "can_edit", "staff_sort_order": 30, "color": "#0891B2", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "nutritionist@example.com", "display_name": "栄養士", "staff_role": "can_edit", "staff_sort_order": 35, "color": "#65A30D", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "office@example.com", "display_name": "事務", "staff_role": "can_edit", "staff_sort_order": 40, "color": "#9333EA", "can_manage_child_records": True, "can_manage_billing_accounts": True},
            {"email": "hiyoko@example.com", "display_name": "ひよこ組担任A", "staff_role": "can_edit", "staff_sort_order": 60, "color": "#F59E0B", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "hiyoko-b@example.com", "display_name": "ひよこ組担任B", "staff_role": "can_edit", "staff_sort_order": 61, "color": "#F97316", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "takenoko@example.com", "display_name": "りす組担任A", "staff_role": "can_edit", "staff_sort_order": 70, "color": "#10B981", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "risu-b@example.com", "display_name": "りす組担任B", "staff_role": "can_edit", "staff_sort_order": 71, "color": "#14B8A6", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "kinoko@example.com", "display_name": "うさぎ組担任A", "staff_role": "can_edit", "staff_sort_order": 80, "color": "#EC4899", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "usagi-b@example.com", "display_name": "うさぎ組担任B", "staff_role": "can_edit", "staff_sort_order": 81, "color": "#F43F5E", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "panda-a@example.com", "display_name": "ぱんだ組担任A", "staff_role": "can_edit", "staff_sort_order": 90, "color": "#8B5CF6", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "panda-b@example.com", "display_name": "ぱんだ組担任B", "staff_role": "can_edit", "staff_sort_order": 91, "color": "#A855F7", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "kirin-a@example.com", "display_name": "きりん組担任A", "staff_role": "can_edit", "staff_sort_order": 100, "color": "#0EA5E9", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "kirin-b@example.com", "display_name": "きりん組担任B", "staff_role": "can_edit", "staff_sort_order": 101, "color": "#38BDF8", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "zou-a@example.com", "display_name": "ぞう組担任A", "staff_role": "can_edit", "staff_sort_order": 110, "color": "#2563EB", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "zou-b@example.com", "display_name": "ぞう組担任B", "staff_role": "can_edit", "staff_sort_order": 111, "color": "#1D4ED8", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "part@example.com", "display_name": "早番パート", "staff_role": "view_only", "staff_sort_order": 150, "color": "#64748B", "can_manage_child_records": False, "can_manage_billing_accounts": False},
            {"email": "arbeit@example.com", "display_name": "遅番パート", "staff_role": "view_only", "staff_sort_order": 151, "color": "#475569", "can_manage_child_records": False, "can_manage_billing_accounts": False},
        ]

        def ensure_user(
            *,
            email: str,
            display_name: str,
            staff_role: str,
            staff_sort_order: int,
            can_manage_child_records: bool,
            can_manage_billing_accounts: bool,
        ) -> User:
            is_calendar_admin = staff_role == "admin"
            user = session.exec(select(User).where(User.email == email)).first()
            if user is None:
                user = User(
                    email=email,
                    display_name=display_name,
                    timezone="Asia/Tokyo",
                    locale="ja-JP",
                    staff_role=staff_role,
                    staff_sort_order=staff_sort_order,
                    is_calendar_admin=is_calendar_admin,
                    can_manage_child_records=can_manage_child_records,
                    can_manage_billing_accounts=can_manage_billing_accounts,
                    provisioning_source=USER_SOURCE_LOCAL_SAMPLE,
                )
            else:
                user.display_name = display_name
                user.timezone = user.timezone or "Asia/Tokyo"
                user.locale = user.locale or "ja-JP"
                user.staff_role = staff_role
                user.staff_sort_order = staff_sort_order
                user.is_calendar_admin = is_calendar_admin
                user.can_manage_child_records = can_manage_child_records
                user.can_manage_billing_accounts = can_manage_billing_accounts
                user.provisioning_source = USER_SOURCE_LOCAL_SAMPLE
                user.is_active = True
                user.updated_at = utc_now()
            session.add(user)
            session.flush()
            return user

        def ensure_member(calendar: Calendar, user: User, role: CalendarMemberRole) -> None:
            member = session.exec(
                select(CalendarMember).where(
                    CalendarMember.calendar_id == calendar.id,
                    CalendarMember.user_id == user.id,
                )
            ).first()
            if member is None:
                member = CalendarMember(calendar_id=calendar.id, user_id=user.id, role=role)
            else:
                member.role = role
                member.updated_at = utc_now()
            session.add(member)
            session.flush()

        def ensure_preference(calendar: Calendar, user: User, *, display_order: int) -> None:
            preference = session.exec(
                select(CalendarUserPreference).where(
                    CalendarUserPreference.calendar_id == calendar.id,
                    CalendarUserPreference.user_id == user.id,
                )
            ).first()
            if preference is None:
                preference = CalendarUserPreference(
                    calendar_id=calendar.id,
                    user_id=user.id,
                    is_visible=True,
                    display_order=display_order,
                )
            else:
                preference.is_visible = True
                preference.display_order = display_order
                preference.updated_at = utc_now()
            session.add(preference)
            session.flush()

        def membership_count(calendar_id) -> int:
            return len(
                session.exec(select(CalendarMember).where(CalendarMember.calendar_id == calendar_id)).all()
            )

        def shared_role_for_user(calendar: Calendar, user: User) -> CalendarMemberRole:
            if user.id == calendar.owner_user_id:
                return CalendarMemberRole.owner
            return CalendarMemberRole.editor if user.can_edit_calendar else CalendarMemberRole.viewer

        active_users = [
            ensure_user(
                email=spec["email"],
                display_name=spec["display_name"],
                staff_role=spec["staff_role"],
                staff_sort_order=spec["staff_sort_order"],
                can_manage_child_records=spec["can_manage_child_records"],
                can_manage_billing_accounts=spec["can_manage_billing_accounts"],
            )
            for spec in staff_specs
        ]
        lead_user = active_users[0]

        for spec, user in zip(staff_specs, active_users):
            personal_calendar = session.exec(
                select(Calendar).where(
                    Calendar.owner_user_id == user.id,
                    Calendar.is_primary.is_(True),
                )
            ).first()
            if personal_calendar is None:
                personal_calendar = session.exec(
                    select(Calendar).where(
                        Calendar.owner_user_id == user.id,
                        Calendar.calendar_type == CalendarType.staff_personal,
                    )
                ).first()
            if personal_calendar is None:
                personal_calendar = Calendar(owner_user_id=user.id)
            personal_calendar.name = f"{user.display_name}の個人カレンダー"
            personal_calendar.calendar_type = CalendarType.staff_personal
            personal_calendar.color = spec["color"]
            personal_calendar.description = "職員ごとの個人用カレンダー"
            personal_calendar.is_primary = True
            personal_calendar.is_archived = False
            personal_calendar.updated_at = utc_now()
            session.add(personal_calendar)
            session.flush()

            ensure_member(personal_calendar, user, CalendarMemberRole.owner)
            ensure_preference(personal_calendar, user, display_order=10)

            user.default_calendar_id = personal_calendar.id
            user.updated_at = utc_now()
            session.add(user)

        rename_map = {
            "A Shared Team": "施設共用カレンダー",
            "B Shared Review": "行事共有カレンダー",
        }
        facility_calendars = []
        for calendar in session.exec(select(Calendar)).all():
            if calendar.name in rename_map:
                calendar.name = rename_map[calendar.name]
            if calendar.is_primary:
                calendar.calendar_type = CalendarType.staff_personal
            elif membership_count(calendar.id) > 1:
                calendar.calendar_type = CalendarType.facility_shared
            if calendar.calendar_type == CalendarType.facility_shared and not calendar.is_archived:
                facility_calendars.append(calendar)
            session.add(calendar)

        if not facility_calendars:
            shared_calendar = Calendar(
                owner_user_id=lead_user.id,
                name="施設共用カレンダー",
                calendar_type=CalendarType.facility_shared,
                color="#059669",
                description="施設全体で共有するカレンダー",
                is_primary=False,
                is_archived=False,
            )
            session.add(shared_calendar)
            session.flush()
            facility_calendars.append(shared_calendar)

        for index, calendar in enumerate(facility_calendars, start=1):
            calendar.calendar_type = CalendarType.facility_shared
            calendar.is_primary = False
            if not calendar.description:
                calendar.description = "施設全体で共有するカレンダー"
            calendar.updated_at = utc_now()
            session.add(calendar)
            owner_user = next((item for item in active_users if item.id == calendar.owner_user_id), lead_user)
            if calendar.owner_user_id != owner_user.id:
                calendar.owner_user_id = owner_user.id
            ensure_member(calendar, owner_user, CalendarMemberRole.owner)
            for user in active_users:
                ensure_member(calendar, user, shared_role_for_user(calendar, user))
                ensure_preference(calendar, user, display_order=20 + index * 10)

        session.commit()


def seed_staff_classroom_assignments() -> None:
    """Give bundled demo homeroom users an explicit current classroom assignment."""
    from models import (
        Classroom,
        StaffClassroomAssignment,
        StaffClassroomAssignmentRole,
        USER_SOURCE_LOCAL_SAMPLE,
        USER_SOURCE_WEB_DEMO,
        User,
    )

    today = local_today()
    fiscal_year_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    with Session(engine) as session:
        classrooms = session.exec(
            select(Classroom).order_by(Classroom.display_order, Classroom.id)
        ).all()
        users = session.exec(
            select(User).where(
                User.is_active.is_(True),
                User.provisioning_source.in_(
                    {USER_SOURCE_LOCAL_SAMPLE, USER_SOURCE_WEB_DEMO}
                ),
            )
        ).all()
        changed = False
        for user in users:
            classroom = next(
                (
                    item
                    for item in classrooms
                    if user.display_name.strip().startswith(
                        item.name.split("（", 1)[0].strip()
                    )
                    and "担任" in user.display_name
                ),
                None,
            )
            if classroom is None or classroom.id is None:
                continue
            existing = session.exec(
                select(StaffClassroomAssignment).where(
                    StaffClassroomAssignment.staff_user_id == user.id,
                    StaffClassroomAssignment.classroom_id == classroom.id,
                    StaffClassroomAssignment.starts_on <= today,
                    (
                        StaffClassroomAssignment.ends_on.is_(None)
                        | (StaffClassroomAssignment.ends_on >= today)
                    ),
                )
            ).first()
            if existing is not None:
                continue
            session.add(
                StaffClassroomAssignment(
                    staff_user_id=user.id,
                    classroom_id=classroom.id,
                    assignment_role=StaffClassroomAssignmentRole.primary,
                    starts_on=fiscal_year_start,
                    is_primary=True,
                    display_order=classroom.display_order,
                )
            )
            changed = True
        if changed:
            session.commit()


