"""機微情報（銀行口座番号・児童医療情報）の AES-256-GCM At-Rest 暗号化テスト。"""
from __future__ import annotations

import os
import unittest
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from models.core import Child, ChildHealthProfile, Classroom, Family, FamilyBillingProfile
from security.crypto import (
    ENCRYPTION_PREFIX,
    EncryptedString,
    decrypt_string,
    encrypt_string,
    mask_account_number,
    mask_name_kana,
)


class CryptoUnitTests(unittest.TestCase):
    """暗号化・復号ユーティリティの単体テスト。"""

    def test_encrypt_and_decrypt_roundtrip(self):
        """日本語・記号・長文テキストが正確に暗号化・復号できること。"""
        cases = [
            "1234567",
            "普通口座 01234567",
            "食物アレルギー（卵・乳・小麦）。アナフィラキシー既往あり。",
            "熱性けいれん歴あり。発熱時はダイアップ投与の指示書あり。",
            "A" * 1000,
        ]
        for original in cases:
            encrypted = encrypt_string(original)
            assert encrypted is not None
            assert encrypted != original
            assert encrypted.startswith(ENCRYPTION_PREFIX)
            decrypted = decrypt_string(encrypted)
            assert decrypted == original

    def test_encryption_is_nondeterministic(self):
        """同一の平文でも暗号化ごとに異なる nonce が使われ、暗号文が異なること。"""
        plain = "sensitive-medical-information"
        enc1 = encrypt_string(plain)
        enc2 = encrypt_string(plain)
        assert enc1 != enc2
        assert decrypt_string(enc1) == plain
        assert decrypt_string(enc2) == plain

    def test_tamper_detection_raises_error(self):
        """暗号文が1バイトでも改ざんされた場合、復号に失敗して例外が送出されること。"""
        plain = "bank-account-number"
        encrypted = encrypt_string(plain)
        assert encrypted is not None
        # ペイロードの一部をビット反転改ざん
        corrupted = encrypted[:-2] + ("A" if encrypted[-2] != "A" else "B") + encrypted[-1]
        with pytest.raises(ValueError, match="復号に失敗しました"):
            decrypt_string(corrupted)

    def test_plaintext_backward_compatibility(self):
        """暗号化されていないレガシー平文データはそのまま読み出せること。"""
        legacy_plaintext = "1234567"
        assert decrypt_string(legacy_plaintext) == legacy_plaintext
        assert decrypt_string(None) is None
        assert decrypt_string("") == ""

    def test_masking_helpers(self):
        """口座番号・カナ氏名のマスキングが適切に動作すること。"""
        assert mask_account_number("1234567") == "***4567"
        assert mask_account_number("1234") == "****"
        assert mask_account_number("12") == "**"
        assert mask_account_number("") == ""
        assert mask_account_number(None) == ""

        assert mask_name_kana("ヤマダタロウ") == "ヤ****ウ"
        assert mask_name_kana("サトウ") == "サ*ウ"
        assert mask_name_kana("アイ") == "ア*"
        assert mask_name_kana("ア") == "*"
        assert mask_name_kana("") == ""


class AtRestEncryptionTests(unittest.TestCase):
    """SQLModel / DB 経由での At-Rest カラム暗号化の統合テスト。"""

    def setUp(self):
        from database import engine, create_db_and_tables
        create_db_and_tables()
        self.engine = engine

    def test_family_billing_profile_account_number_is_encrypted_at_rest(self):
        """FamilyBillingProfile.account_number が DB 内部で暗号化されて保存されること。"""
        suffix = uuid4().hex[:8]
        raw_account_number = "9876543"

        with Session(self.engine) as session:
            # 家族作成
            family = Family(family_name=f"暗号化テスト家族_{suffix}")
            session.add(family)
            session.commit()
            session.refresh(family)

            # 口座情報登録（平文を代入）
            profile = FamilyBillingProfile(
                family_id=family.id,
                customer_number=f"CUST_{suffix}",
                bank_code="0001",
                branch_code="001",
                account_type="1",
                account_number=raw_account_number,
                account_holder_kana="テストタロウ",
            )
            session.add(profile)
            session.commit()
            profile_id = profile.id

        # 1. ORM 経由で再取得: 透過的に平文として読み出せること
        with Session(self.engine) as session:
            loaded = session.get(FamilyBillingProfile, profile_id)
            assert loaded is not None
            assert loaded.account_number == raw_account_number
            # マスク表示プロパティの検証
            assert loaded.account_number_masked == "***6543"
            assert loaded.account_holder_kana_masked == "テ****ウ"

        # 2. Raw SQL で DB から直接取得: DB 内部には暗号文（v1:...）として記録され、平文が漏洩していないこと
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT account_number FROM family_billing_profiles WHERE id = :id"),
                {"id": profile_id},
            ).fetchone()
            assert row is not None
            db_stored_value = row[0]
            # DB 内に平文は保存されていない
            assert db_stored_value != raw_account_number
            assert raw_account_number not in db_stored_value
            # v1: プレフィックスの暗号文として保存されている
            assert db_stored_value.startswith(ENCRYPTION_PREFIX)

    def test_child_health_profile_medical_notes_are_encrypted_at_rest(self):
        """ChildHealthProfile の既往歴・医療的ケア情報が DB 内部で暗号化されること。"""
        suffix = uuid4().hex[:8]
        medical_text = "心臓疾患の既往あり。激しい運動時は呼吸に注意すること。"

        with Session(self.engine) as session:
            classroom = Classroom(name=f"暗号化組_{suffix}", display_order=99)
            session.add(classroom)

            family = Family(family_name=f"医療テスト家族_{suffix}")
            session.add(family)
            session.commit()
            session.refresh(classroom)
            session.refresh(family)

            child = Child(
                first_name="花子",
                last_name="医療",
                first_name_kana="ハナコ",
                last_name_kana="イリョウ",
                birth_date=date(2021, 5, 5),
                enrollment_date=date(2024, 4, 1),
                classroom_id=classroom.id,
                family_id=family.id,
            )
            session.add(child)
            session.commit()
            session.refresh(child)

            health = ChildHealthProfile(
                child_id=child.id,
                requires_medical_care=True,
                medical_history=medical_text,
                medical_care_details="毎日13時に服薬確認",
            )
            session.add(health)
            session.commit()
            health_id = health.id

        # 1. ORM 経由で取得: 透過的復号
        with Session(self.engine) as session:
            loaded = session.get(ChildHealthProfile, health_id)
            assert loaded is not None
            assert loaded.medical_history == medical_text
            assert loaded.medical_care_details == "毎日13時に服薬確認"

        # 2. Raw SQL で直接取得: 暗号化されていること
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT medical_history FROM child_health_profiles WHERE id = :id"),
                {"id": health_id},
            ).fetchone()
            assert row is not None
            stored_val = row[0]
            assert stored_val != medical_text
            assert medical_text not in stored_val
            assert stored_val.startswith(ENCRYPTION_PREFIX)
