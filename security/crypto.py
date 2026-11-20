"""Security and cryptographic helpers for open-hoikuict."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from typing import Any, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import String, TypeDecorator

logger = logging.getLogger(__name__)

# 暗号文のバージョンプレフィックス（後方互換性・平文検出用）
ENCRYPTION_PREFIX = "v1:"

# デフォルトのソルト
_DEFAULT_DEV_KEY_MATERIAL = "open-hoikuict-dev-encryption-key-do-not-use-in-production"


def _get_encryption_key() -> bytes:
    """環境変数から 256-bit (32 bytes) 暗号化キーを導出する。"""
    raw_key = os.getenv("HOIKUICT_ENCRYPTION_KEY") or os.getenv("HOIKUICT_SECRET_KEY")
    if not raw_key:
        if os.getenv("HOIKUICT_ENV") == "production":
            raise RuntimeError(
                "本番環境（HOIKUICT_ENV=production）では HOIKUICT_ENCRYPTION_KEY または "
                "HOIKUICT_SECRET_KEY の設定が必須です。"
            )
        raw_key = _DEFAULT_DEV_KEY_MATERIAL
    # SHA-256 で確実に 32 バイトのバイナリ鍵を導出
    return hashlib.sha256(raw_key.encode("utf-8")).digest()


def encrypt_string(plain_text: str | None) -> str | None:
    """文字列を AES-256-GCM で暗号化し、v1:<base64> 形式で返す。

    None または空文字列はそのまま返す。
    """
    if plain_text is None:
        return None
    if plain_text == "":
        return ""
    if plain_text.startswith(ENCRYPTION_PREFIX):
        # 既に暗号化済みの場合は再暗号化しない
        return plain_text

    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    # 96-bit (12 bytes) の暗号論的擬似乱数 nonce
    nonce = secrets.token_bytes(12)
    # 暗号化（タグは暗号文末尾に含まれる）
    ciphertext = aesgcm.encrypt(nonce, plain_text.encode("utf-8"), None)
    # nonce + ciphertext を base64 エンコード
    payload = base64.b64encode(nonce + ciphertext).decode("ascii")
    return f"{ENCRYPTION_PREFIX}{payload}"


def decrypt_string(cipher_text: str | None) -> str | None:
    """v1:<base64> 形式の暗号文を復号して元の文字列を返す。

    平文（プレフィックスなし）の場合はそのまま返す（安全な後方互換性）。
    """
    if cipher_text is None:
        return None
    if not cipher_text.startswith(ENCRYPTION_PREFIX):
        # 暗号化されていないレガシー平文データはそのまま返す
        return cipher_text

    payload_b64 = cipher_text[len(ENCRYPTION_PREFIX) :]
    try:
        raw = base64.b64decode(payload_b64.encode("ascii"))
        if len(raw) < 12 + 16:  # nonce (12) + min tag (16)
            logger.error("暗号文ペイロード長が不足しています")
            return cipher_text
        nonce = raw[:12]
        ciphertext = raw[12:]
        key = _get_encryption_key()
        aesgcm = AESGCM(key)
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("復号処理中にエラーが発生しました: %s", exc)
        raise ValueError(f"復号に失敗しました: {exc}") from exc


def mask_account_number(account_number: str | None) -> str:
    """口座番号をマスク表示する（下4桁を残し、それ以外を * に変換）。

    例: '1234567' -> '***4567', '123' -> '***'
    """
    if not account_number:
        return ""
    # 復号されていることを担保
    plain = decrypt_string(account_number) or ""
    clean = plain.strip()
    if len(clean) <= 4:
        return "*" * len(clean)
    return "*" * (len(clean) - 4) + clean[-4:]


def mask_name_kana(name_kana: str | None) -> str:
    """カナ氏名をマスク表示する（先頭と末尾を残し、中央を * に変換）。

    例: 'ヤマダタロウ' -> 'ヤ****ウ'
    """
    if not name_kana:
        return ""
    plain = decrypt_string(name_kana) or ""
    clean = plain.strip()
    if len(clean) <= 2:
        return clean[:1] + "*" if len(clean) == 2 else "*"
    return clean[0] + "*" * (len(clean) - 2) + clean[-1]


class EncryptedString(TypeDecorator):
    """SQLAlchemy 用の透過的 AES-256-GCM カラム暗号化型。

    DB 保存時に自動で暗号化（v1:<base64>）し、
    取得時に自動で復号して Python str を返す。
    DB 上に平文が存在する場合も自動検出して透過的に復号可能。
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int = 512, **kwargs: Any) -> None:
        # 暗号文（Base64 + nonce + tag）は平文より長くなるため、デフォルト 512 に拡張
        super().__init__(length=length, **kwargs)

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        del dialect
        if value is None:
            return None
        return encrypt_string(str(value))

    def process_result_value(self, value: Any, dialect: Any) -> Optional[str]:
        del dialect
        if value is None:
            return None
        return decrypt_string(str(value))
