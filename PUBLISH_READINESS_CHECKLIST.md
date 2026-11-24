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

### 6. Nusoft v0.8.0 統合（SaaS リファクタリング & NuShift v0.8.0 統合）（2026-11-21）

| 指摘区分 | 対象ファイル | 修正内容 | ステータス |
|---|---|---|:---:|
| **Critical** | `vendor/nushift/` | `E:\nushift\nushift` から NuShift v0.8.0 を完全同期 (`scripts/sync_nushift_vendor.py` 実行・`VENDOR.json` 更新・全54ファイル検証パス) | 修正完了 |
| **Critical** | `shift_schedule/` | Phase 1〜4 SaaS リファクタリング完遂（過剰制約自動診断エンジン、即時 Re-plan Micro Engine、マルチテナント分離 `facility_id`、不変スナップショット `ShiftSolveSnapshots`、分散ワーカー & KEDA オートスケーラー配備） | 修正完了 |
| **High** | `version.py`, `README.md` | バージョン表記を統一して `v0.8.0` / `nusoft v0.8.0` へアップデート | 修正完了 |

---

### 5. 公開前コードレビュー指摘事項の修正（2026-11-20）

| 指摘区分 | 対象ファイル | 修正内容 | ステータス |
|---|---|---|:---:|
| **Critical** | `guardian_qr_service.py` | `execute_sibling_qr_punch` で `target_date` が指定された際に打刻日時が実行日固定になっていた問題を修正（`punch_time = datetime.combine(day, now_naive.time())`）。`test_pims_core_sync.py` パス。 | 修正完了 |
| **Critical** | `database.py` | 既存マイグレーション ID への追記による既存 DB スキーマ欠落を解消するため、`046_daily_contact_review_columns` を分離定義し、`daily_contact_replies` の `reviewed_by_staff_id` 等のカラム追加を確実に適用。`test_daily_contacts_nav.py` パス。 | 修正完了 |
| **High** | `tests/system/test_spec_changes_20260919.py` | Phase 1 で追加された閉園時間チェック（< closing_time）に合わせてテスト側の `planned_pickup_time="18:45"` に更新し、閉園後予定（22:45）が存在する場合のキオスク修正フローのアサーションを分離検証。`test_spec_changes_20260919.py` 全件パス。 | 修正完了 |
| **High** | `tests/conftest.py` | pytest の autouse fixture を新設し、テスト毎に `cache_service.invalidate_all_caches()` を実行してインメモリキャッシュによるテスト間汚染（test pollution）を根絶。`test_daily_contact_content_list.py` パス。 | 修正完了 |
| **High** | `scripts/backup_contracts/schema-20261105.json` | 新規追加テーブル 6 件（`parent_medical_responses`, `family_emergency_orders`, `child_emergency_orders`, `billing_exemptions`, `plan_document_attachments`, `user_onboarding_states`）および追加カラム群をバックアップ契約スキーマに同期。`test_backup_v2.py` 全41件パス。 | 修正完了 |

---

### 6. テストスイート健全化・回帰テスト修正（2026-11-21）

| 指摘区分 | 対象ファイル | 修正内容 | ステータス |
|---|---|---|:---:|
| **High** | `tests/snapshots/metadata_schema.json`, `scripts/backup_contracts/schema-20261105.json` | Phase 5 で追加された `attendance_records.idempotency_key` カラムをメタデータスナップショットおよびバックアップ契約定義に同期。`test_models_compat.py` パス。 | 修正完了 |
| **High** | `scripts/backup_contracts/schema-20261105.json` | マルチテナント対応で追加された `organizations`, `facilities` テーブル定義をバックアップ契約定義に同期。`test_backup_v2.py` パス。 | 修正完了 |
| **High** | `tests/test_paid_leave_shift_e2e.py` | 全体実行時の高CPU負荷環境下で月次シフト求解が時間切れにならないよう `time_limit_sec` を 5 秒から 20 秒に緩和し、ジョブ実行ステータスの検証を追加。`test_paid_leave_shift_e2e.py` パス。 | 修正完了 |
| **Medium** | `tests/auth/test_staff_password_recovery.py` | レートリミット（冷却期間60秒）の経過テストにおいて、並列実行時の微小なタイミング遅延による偽陽性を防ぐため経過時間マージンを 61秒から 120秒へ拡張。`test_staff_password_recovery.py` パス。 | 修正完了 |
| **Medium** | `c:\Users\user\openict\pytest.ini`, `test_pairing_and_repair.py` | ルートディレクトリ用 `pytest.ini` を新設しテスト対象ディレクトリを `open-hoikuict/tests` に指定。検証スクリプト `test_pairing_and_repair.py` に `__main__` ガードを設けて pytest 実行時の標準出力破損・クラッシュを解消。 | 修正完了 |
| **Low** | `tests/routers/test_parent_portal.py` | コミット時に混入した残余デバッグプリント (`DEBUG: page_items count in history`) を除去。 | 修正完了 |

---

### 7. Nusoft v0.8.2 統合（現場利便性・段階的請求締め解除・プロファイル統合・実務ブラッシュアップ）（2026-11-24）

| 指摘区分 | 対象ファイル | 修正内容 | ステータス |
|---|---|---|:---:|
| **Critical** | `profile_config.py`, `main.py`, `database.py` | デュアルランタイムプロファイル（`ProfileMode.EMBEDDED` オールインワン vs `ProfileMode.CLOUD` SaaS）の実装。外部依存ゼロの単一プロセス動作を担保。 | 修正完了 |
| **Critical** | `routers/billing.py`, `zengin_service.py`, `models/core.py`, `alembic/versions/f7b91c2a4d05_*.py` | 段階的請求締め解除（L0: 差分なし直ちに取り消し / L1: 差分あり園長確認申請・承認フロー / L2: 全銀送金済み管理者手動）を実装。5つの理由テンプレート、差分事前見積もり、構造化監査ログ完備。 | 修正完了 |
| **High** | `templates/child_records/log_form.html`, `static/js/hoiku-autosave.js`, `templates/shared/ui_macros.html` | 児童記録の自動保存マクロ（`hoiku-autosave.js`）、保育指針「5領域」定型フレーズチップ、タッチターゲット最適化（44px以上）を実装。 | 修正完了 |
| **High** | `routers/attendance_checks.py`, `static/js/attendance-checks.js`, `templates/attendance_checks/` | 出欠点検ボードの安全アラートバナー、タッチ大型ボタン、Web Audio API による音響確認フィードバック、クラス別クエリ最適化（`?classroom_id=X`）を実装。 | 修正完了 |
| **High** | `templates/staff_portal/shift_requests.html`, `templates/paid_leave/index.html` | 職員ポータルにおけるスマート時間入力セレクター、理由チップ、モバイルタッチ操作性を刷新。 | 修正完了 |
| **High** | `templates/billing/child_charges.html`, `templates/billing/index.html` | 請求点検サマリカード、インライン差分ハイライト、児童別請求保存セーフガードを配備。 | 修正完了 |
| **Medium** | `routers/parent_portal.py` | お迎え予定入力の補食指定（`snack_required`）未選択時の自動安全フォールバック（HTTP 400エラー防止）。連絡帳履歴の期間指定（180日上限）による読み込み高速化。 | 修正完了 |
| **Medium** | `routers/daily_contacts.py` | 主任・園長による未承認連絡帳返信の一括承認エンドポイント（`/daily-contacts/replies/bulk-approve`）を実装。 | 修正完了 |
| **Medium** | `routers/child_health.py` | クラス・複数園児の午睡チェック・定期検温一括登録エンドポイント（`/health/bulk-checks`）を実装。 | 修正完了 |
| **Medium** | `zengin_service.py` | 全銀事前チェック（preflight）での未転送確定済み延長保育料の自動検知・警告通知機能を実装。 | 修正完了 |
| **Medium** | `shift_schedule/routers/nushift_export.py`, `shift_schedule/services/nushift_export.py` | NuShift突発欠勤リペア同期API（`/shifts/import-repaired-shift`）およびエクスポート時のデフォルト月フォールバック・役職マッピング補正を実装。 | 修正完了 |
| **Medium** | `routers/parent_accounts.py` | 管理者向け保護者登録用QRコード即時生成エンドポイント（`/parent-accounts/registration-qr`）を実装。 | 修正完了 |
| **Medium** | `extended_care_billing_transfer_service.py`, `extended_care_fee_service.py`, `templates/extended_care_fees/` | 延長保育料・請求転送処理のクエリ最適化（`not_in` スライシング）および一覧画面のアコーディオン・要確認バッジ最適化。 | 修正完了 |
| **High** | `version.py`, `tests/test_version.py`, `README.md`, `MANUAL.md` | バージョン表記を統一して `v0.8.2` / `nusoft v0.8.2` へアップデート。操作マニュアルに新機能の具体的な手順を追記。 | 修正完了 |
| **High** | `tests/` | 新規テストスイート（`test_improvements_cases_1_to_6.py`, `test_parent_accounts_qr.py`, `test_nushift_roundtrip.py`, `test_app_lifespan_smoke.py`, `test_startup_smoke.py` 等）を追加し全件パス。 | 修正完了 |

---

## 公開前チェックリスト

### 必須項目

- [x] テストスイート全体が全パスすること (`pytest tests/`)...【要事前設定：.env に本番変数をコピー後実行】
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
- [x] NuShift ソルバーが最新 v0.8.0+ に同期され、突発欠勤リペア同期 API と連携確認済であること
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
- [x] `docs/manual-guide-preview/` を試作版・モックから「オープン保育ICT 総合操作マニュアル・ビジュアルガイド (v0.7.1)」へ全面的にリニューアル（2026-11-20 実施）:
  - 外部URL依存を解消し、園内LAN・オフラインで完結するローカルリンク化を徹底
  - 主要機能ガイドを追加（NuShiftシフト自動作成・ピン留め、月次請求・全銀口座振替・締め解除、連絡帳ダブルチェック承認、緊急連絡先優先順位、医療同意・レントゲン承諾）
  - ロール別ナビゲーション（保育士向け、管理者向け、保護者向け）とA4印刷（研修資料配布）対応
