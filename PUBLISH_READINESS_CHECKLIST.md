# 公開前チェックリスト - open-hoikuict

## 実施済みの調査・修正

### 1. テスト失敗の特定と修正

**ファイル**: `tests/routers/test_billing_zengin.py`

**問題**: 2件のテスト失敗
- `test_zengin_download_requires_admin`: 期待 200、実際 403
- `test_invalid_result_file_returns_422_without_importing`: 期待 422、実際 403

**根本原因**: `StaffUser(role=Role.ADMIN, user_id=None)` で `get_live_staff_user()` が `None` を返し、権限チェック (`require_zengin_exporter`) で 403 が返される。モック認証の `StaffUser` に `user_id` が設定されていないため、DB 上の `User` レコードを取得できない。

**修正**: `setUp()` で admin User レコードを DB に作成し、`StaffUser` に `user_id` を設定。
```python
with Session(self.engine) as session:
    admin_id = self._create_admin_user(session)
    session.commit()
self.current_user = StaffUser(role=Role.ADMIN, name="園長", user_id=admin_id)
```

### 2. セキュリティ設定レビュー (`security_config.py`)

本番環境 (`HOIKUICT_ENV=production`) に対して以下の厳格チェックが実装済み：

| チェック項目 | 要件 | ステータス |
|-------------|------|-----------|
| モック認証 | 無効必須 | 実装済み |
| CSRF 適用 | `HOIKUICT_CSRF_ENFORCE=1` | 実装済み |
| セキュア Cookie | `HOIKUICT_COOKIE_SECURE=1` | 実装済み |
| SECRET KEY | 32文字以上 | 実装済み |
| スタッフ認証 | `local_password` | 実装済み |
| 親認証 | `local_password` | 実装済み |
| 信頼プロキシ | `FORWARDED_ALLOW_IPS` (IP/CIDR, `*` 禁止) | 実装済み |
| 親メール | `smtp` 必須 | 実装済み |
| 登録 URL | HTTPS 必須 | 実装済み |
| SMTP 設定 | ホスト/ポート/From/STARTTLS=1 | 実装済み |
| パスワードブロックリスト | ファイル必須 | 実装済み |
| キオスクモード | production では `open` 禁止 | 実装済み |
| プッシュ通知 | production では `capture` 禁止 | 実装済み |
| ワーカー数 | 単一ワーカー必須 | 実装済み |

### 3. .env.example の開発デフォルト (注意)

開発用デフォルトに非安全な設定を含むが、これは開発専用。本番漏洩防止が重要：

| 変数 | 開発値 | 本番要件 |
|------|--------|---------|
| `HOIKUICT_CSRF_ENFORCE` | `0` | `1` |
| `HOIKUICT_KIOSK_ACCESS_MODE` | `open` | `disabled` または `token` |
| `HOIKUICT_ENABLE_MOCK_AUTH` | `1` | 未設定 (disabled) |

---

## 公開前チェックリスト

### 必須項目

- [ ] テストスイート全体が全パスすること (`pytest tests/`)
- [ ] 本番環境変数がすべて設定されていること (`security_config.validate_runtime_security()` が通過)
- [ ] `HOIKUICT_SECRET_KEY` が32文字以上のランダム値であること
- [ ] `HOIKUICT_LOGIN_THROTTLE_HMAC_KEY` が32バイト以上であること
- [ ] `HOIKUICT_PASSWORD_BLOCKLIST_PATH` が指定され、ファイルが存在すること
- [ ] `FORWARDED_ALLOW_IPS` に信頼するリバースプロキシのIP/CIDRが設定されていること (`*` 禁止)
- [ ] SMTP 設定がすべて完了していること (ホスト、ポート、From、STARTTLS=1)
- [ ] HTTPS 証明書が設定されていること (登録URL、リカバリーURL)
- [ ] キオスクアクセスモードが `open` 以外であること
- [ ] プッシュ通知トランスポートが `capture` 以外であること
- [ ] シングルワーカー設定であること (または `HOIKUICT_ALLOW_MULTIWORKER_RATE_LIMIT=1`)

### 推奨項目

- [ ] CSRF トークンの HMAC 署名検証が正しく動作すること
- [ ] セキュリティヘッダー (CSP, HSTS, X-Frame-Options: DENY など) がすべてのレスポンスに付与されること
- [ ] CSV インポートで数式インジェクション対策が適用されていること
- [ ] ファミリーアーカイブ/削除が監査ログ付きで状態遷移すること
- [ ] Zengin ファイル形式 (cp932, 120バイトレコード) が正しく出力・解析されること
- [ ] 請求計算の丸め処理 (proration rounding) が正しく動作すること
- [ ] パスワードハッシュが argon2 であること
- [ ] ログインスロットリング (throttling) が有効であること
- [ ] MFA コード検証が正しく動作すること
- [ ] セッショントークンの失効が正しく動作すること

### ドキュメント項目

- [ ] `.env.example` をコピーして `.env` を作成する手順が文書化されていること
- [ ] 本番デプロイ手順 (Docker, systemd など) が文書化されていること
- [ ] 環境変数の一覧と説明が文書化されていること
- [ ] セキュリティインシデント対応手順が文書化されていること

---

- `tests/routers/test_billing_zengin.py` - `setUp()` で admin User レコード作成、`user_id` 設定を追加

- `tests/routers/test_billing_zengin.py` - `setUp()` で admin User レコード作成、`user_id` 設定を追加
