from __future__ import annotations

from datetime import date
from sqlmodel import Session, SQLModel, create_engine

import cache_service
from models import Child, ChildStatus, Classroom, FacilitySettings


def test_cache_service_lifecycle():
    engine = create_engine("sqlite:///:memory:", echo=False)
    SQLModel.metadata.create_all(engine)

    cache_service.invalidate_all_caches()

    with Session(engine) as session:
        # 1. クラスルームキャッシュのテスト
        cls1 = Classroom(name="さくら組", capacity=15)
        cls2 = Classroom(name="ひまわり組", capacity=20)
        session.add(cls1)
        session.add(cls2)
        session.commit()

        classrooms_1 = cache_service.get_cached_classrooms(session)
        assert len(classrooms_1) == 2
        assert {c.name for c in classrooms_1} == {"さくら組", "ひまわり組"}

        # DBに新しいクラスを追加（キャッシュパージ前）
        cls3 = Classroom(name="たんぽぽ組", capacity=10)
        session.add(cls3)
        session.commit()

        # キャッシュが効いているため、まだ2件
        classrooms_cached = cache_service.get_cached_classrooms(session)
        assert len(classrooms_cached) == 2

        # パージ実行
        cache_service.invalidate_classrooms_cache()

        # パージ後は3件取得できる
        classrooms_fresh = cache_service.get_cached_classrooms(session)
        assert len(classrooms_fresh) == 3

        # 2. 施設設定キャッシュのテスト
        setting = FacilitySettings(fever_return_days=2, fever_caution_c=37.5)
        session.add(setting)
        session.commit()

        settings_1 = cache_service.get_cached_facility_settings(session)
        assert settings_1 is not None
        assert settings_1.fever_return_days == 2

        # 設定変更
        setting.fever_return_days = 3
        session.add(setting)
        session.commit()

        # キャッシュからはまだ旧値
        cached_set = cache_service.get_cached_facility_settings(session)
        assert cached_set is not None
        assert cached_set.fever_return_days == 2

        # パージ
        cache_service.invalidate_facility_settings_cache()
        fresh_set = cache_service.get_cached_facility_settings(session)
        assert fresh_set is not None
        assert fresh_set.fever_return_days == 3

        # 3. 在園児キャッシュのテスト
        child1 = Child(
            first_name="太郎",
            last_name="山田",
            first_name_kana="タロウ",
            last_name_kana="ヤマダ",
            status=ChildStatus.enrolled,
            birth_date=date(2022, 5, 1),
            enrollment_date=date(2023, 4, 1),
        )
        child2 = Child(
            first_name="花子",
            last_name="鈴木",
            first_name_kana="ハナコ",
            last_name_kana="スズキ",
            status=ChildStatus.graduated,
            birth_date=date(2020, 3, 1),
            enrollment_date=date(2021, 4, 1),
        )
        session.add(child1)
        session.add(child2)
        session.commit()

        active_children = cache_service.get_cached_active_children(session)
        assert len(active_children) == 1
        assert active_children[0].first_name == "太郎"

        cache_service.invalidate_all_caches()
