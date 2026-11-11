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

### 4. 公開前コードレビュー指摘事項の修正（2026-11-11）

| 指摘区分 | 対象ファイル | 修正内容 | ステータス |
|---|---|---|:---:|
| **Critical** | `csrf.py`, `templates/guardian/kiosk.html` | `/guardian/qr/` を CSRF 免除プレフィックスに追加、およびキオスク fetch に `X-CSRF-Token` ヘッダーを付与（本番 403 遮断の完全解消） | 修正完了 |
| **Critical** | `routers/pims_attendance.py` | 園児マスタ管理 (`/children/*`)・CSV 出力 (`/export/*`)・取込 (`/import/*`) に職員ログイン (`get_current_staff_user`) および権限ガード (`require_child_record_manager`, `require_document_exporter`) を適用 | 修正完了 |
| **Critical** | `pims_service.py` | PIMS 公式 9 列 CSV および降園抜け CSV 出力に `sanitize_csv_cell` (CWE-1236 対策) を適用 | 修正完了 |
| **High** | `templates/guardian/kiosk.html` | 園児個別打刻画面 (`selected_child` 選択時) において QR モーダル・スキャナーを描画しないようガード（文言衝突による回帰テスト 3 件失敗の解消） | 修正完了 |
| **High** | `tests/snapshots/metadata_schema.json` | `facility_settings.parent_billing_portal_enabled` をスナップショットに追記 (`test_models_compat.py` パス) | 修正完了 |
| **High** | `scripts/backup_contracts/schema-20261105.json` | `parent_billing_portal_enabled`, `punch_children`, `punch_logs` を契約定義に追記 (`test_backup_v2.py` パス) | 修正完了 |
| **High** | `vendor/nushift/` | `python scripts/sync_nushift_vendor.py --source E:\nushift\nushift` を実行し NuShift v0.5.0 ソルバーを同期 (`test_vendor_sync.py` パス) | 修正完了 |
| **High** | `alembic/versions/` | `parent_billing_portal_enabled` および `punch_children`, `punch_logs` テーブル作成のマイグレーション (`e1f54a7b30d4`) を新規作成 | 修正完了 |
| **Medium** | `parent_billing_service.py` | `family_id=None` に対する防御的ガード (`if not family_id: return ...`) を追加 | 修正完了 |
| **Medium** | `routers/pims_attendance.py` | PIMS 帳票ダウンロード時に `log_export()` による監査ログ記録を追加 | 修正完了 |
| **Medium** | `tests/test_pims_attendance.py` | 専用の管理者UUIDを使用し teardown で削除することで、`test_document_exports.py` 等へのテスト間状態汚染を防止 | 修正完了 |
| **Low** | `pims_service.py`, `routers/pims_attendance.py` | 未使用インポート (`Classroom`, `monthrange`, `date`, `HTTPException`) を削除し `ruff check .` 全件 Green | 修正完了 |

---

## 公開前チェックリスト

### 必須項目

- [x] テストスイート全体が全パスすること (`pytest tests/`)
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

- [x] CSRF トークンの HMAC 署名検証が正しく動作すること（キオスク QR 打刻を含む）
- [ ] セキュリティヘッダー (CSP, HSTS, X-Frame-Options: DENY など) がすべてのレスポンスに付与されること
- [x] CSV インポート・エクスポートで数式インジェクション対策が適用されていること（PIMS CSV 含む）
- [x] 園児マスタ・PIMS 帳票エクスポートの認可制御および監査ログ記録が適用されていること
- [x] Alembic マイグレーションが最新（`e1f54a7b30d4`）であること
- [x] NuShift ソルバーが最新 v0.5.0 に同期されていること
- [ ] ファミリーアーカイブ/削除が監査ログ付きで状態遷移すること
- [ ] Zengin ファイル形式 (cp932, 120バイトレコード) が正しく出力・解析されること
- [ ] 請求計算の丸め処理 (proration rounding) が正しく動作すること
- [ ] パスワードハッシュが argon2 であること
- [ ] ログインスロットリング (throttling) が有効であること
- [ ] MFA コード検証が正しく動作すること
- [ ] セッショントークンの失効が正しく動作すること
- [ ] 保護者MFA（`HOIKUICT_PARENT_LOGIN_MFA`）を無効から有効に変更した場合、切替前に発行された保護者セッションが残存するため、`revoke_parent_sessions`（`parent_auth.py`）で一括失効させる運用手順を文書化すること

### ドキュメント項目

- [ ] `.env.example` をコピーして `.env` を作成する手順が文書化されていること
- [ ] 本番デプロイ手順 (Docker, systemd など) が文書化されていること
- [ ] 環境変数の一覧と説明が文書化されていること
- [ ] セキュリティインシデント対応手順が文書化されていること
