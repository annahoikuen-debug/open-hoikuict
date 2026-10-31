# 回帰防止テスト計画書 — open-hoikuict (Project A)

バージョン: nusoft v0.4.0  
作成日: 2026-10-31  
対象リポジトリ: `C:\Users\user\openict\open-hoikuict\`

---

## 1. テスト戦略

### 1.1 単体テスト（関数・クラス単位）
個別モジュールの純粋関数・クラスメソッドを、DBや外部サービスに依存せず検証する。
対象: `rate_limiter.py`, `security_headers.py`, `zengin_service.py`, `extended_care_fee_service.py`, `auth.py`, `local_auth.py`, `parent_auth.py`, `audit_logger.py`, `csrf.py` など。

### 1.2 結合テスト（API エンドポイント、DB 連携）
FastAPI `TestClient` を用いたルーター単位の結合テスト。SQLModel セッションをインメモリ/一時DBで実行し、エンドポイント → サービス → DB の一連を検証する。
対象: `tests/routers/` 配下（スタッフ認証、保護者ポータル、請求・Zengin、キオスク、シフト最適化エンドポイントなど）。

### 1.3 E2E テスト（主要ユーザーフロー）
職員ログイン → シフト作成 → 出欠管理 → 請求計算 → Zengin 出力、および保護者ポータル登録 → ログイン → 出欠確認 の主要フローをシナリオ単位で検証する。
対象: `tests/system/`, `tests/test_paid_leave_shift_e2e.py` など。

### 1.4 セキュリティテスト（認証、認可、レート制限、ヘッダー）
- 認証: スタッフ/保護者ログイン、MFA、パスワード変更、アカウント停止
- 認可: ロールベースアクセス制御（view_only / can_edit / admin）
- レート制限: ログイン試行、MFAコード送信・検証、パスワード再設定
- セキュリティヘッダー: CSP、X-Frame-Options、X-Content-Type-Options、HSTS、Referrer-Policy
- CSRF: トークンローテーション、セッションクリア時のトークン再発行
- 監査ログ: PII マスク、JSON Lines 形式、イベント記録

### 1.5 パフォーマンス・回帰テスト（シフト求解時間、メモリリーク）
- CBC/HiGHS ソルバーの求解時間上限遵守
- 大規模データ投入時のメモリ使用量変化（リーク検出）
- 繰り返し求解後の同一性（決定論的な解の再現性）

---

## 2. テストカテゴリと対象（Project A）

| カテゴリ | 対象モジュール・機能 | 検証項目 |
|---|---|---|
| 認証・認可 | `staff_auth`, `parent_auth`, `MFA`, セッション管理 | ログイン成功/失敗、MFA 送信・検証、パスワード変更、アカウント停止・復帰、セッション期限切れ、ロールベースアクセス制御 |
| シフト最適化 | CBC/HiGHS ソルバー、配置基準、BLOCKER ゲート、ピン留め | 求解成功、制約充足、BLOCKER による ERROR ステータス、ピン留めセルの固定、ギャップ検知 |
| 登降園・出欠 | キオスク打刻、保護者ポータル、ギャップ検知 | 打刻記録、在園児数計算、ギャップ検出、保護者ポータルからの出欠確認 |
| 請求・Zengin | 延長保育料計算、全銀フォーマット出力 | 延長料金計算（猶予・丸め・上限）、Zengin ヘッダー/データ/トレーラ/エンドレコード、120バイトレコード検証 |
| セキュリティ | CSP ヘッダー、レート制限、監査ログ、CSRF | セキュリティヘッダー付与、CSP nonce、レート制限ブロック、PII マスク、CSRF トークンローテーション |
| バックアップ・リストア | データベーススナップショット、整合性検証 | バックアップ作成・リストア、整合性チェック、リストア後のデータ検証 |

---

## 3. テストファイル構成

### 3.1 既存テストファイル
- `tests/test_audit_logger.py` — 監査ログ（PII マスク、JSON Lines）
- `tests/test_rate_limiter.py` — レート制限
- `tests/test_security_headers.py` — セキュリティヘッダー
- `tests/test_mfa_rate_limit.py` — MFA レート制限
- `tests/test_staff_auth_rate_limit.py` — スタッフログインレート制限
- `tests/test_parent_auth_rate_limit.py` — 保護者ログインレート制限
- `tests/test_cbc_solver_environment.py` — CBC ソルバー環境
- `tests/test_solve_jobs_highs.py` — HiGHS 求解
- `tests/test_shift_schedule_steps12_16.py` — シフトスケジュール
- `tests/routers/test_billing_zengin.py` — 請求・Zengin エンドポイント
- `tests/services/test_backup_*.py` — バックアップ・リストア

### 3.2 新規回帰テストファイル（本計画で追加）

| ファイル | カテゴリ | 主要検証項目 |
|---|---|---|
| `tests/test_regression_auth.py` | 認証・認可 | スタッフ/保護者ログイン、MFA、パスワード変更、アカウント停止・復帰 |
| `tests/test_regression_shift.py` | シフト最適化 | 求解、BLOCKER、ピン留め、ギャップ検知 |
| `tests/test_regression_billing.py` | 請求・Zengin | 延長料金計算、全銀フォーマット出力 |
| `tests/test_regression_security.py` | セキュリティ | セキュリティヘッダー、レート制限、CSP |

---

## 4. CI/CD 統合

### 4.1 プリコミットフック
- `ruff check .` — コミット前に実行。E9（構文エラー）と F（未使用インポート等）を検出。

### 4.2 プルリクエスト時のテスト実行
- プルリクエスト作成・更新時に `python -m pytest tests/ -x -q` を実行。
- 新規テストファイル（`test_regression_*.py`）も含めて全テストがパスすることをマージ条件とする。
- pre-existing failure を修正しない限り、CI は赤になる可能性があるため、ベースラインとして既知の失敗を記録する。

### 4.3 カバーレーショ閾値（80%以上）
- `pytest-cov` を用いてカバレッジを測定。
- 全プロジェクトでカバレッジ 80% 以上を目標。
- `make cov`（Project B）または `python -m pytest --cov=. --cov-report=term-missing`（Project A）で測定。

### 4.4 回帰テストの自動実行スケジュール
- 毎日定時（例: 深夜 2 時）にフルテストスイートを自動実行。
- 週次でパフォーマンス回帰テスト（シフト求解時間、メモリリーク）を実行。
- 失敗検出時に Slack/メール通知を送信。

---

## 5. カバレッジ目標

| カテゴリ | 目標カバレッジ |
|---|---|
| 認証・認可 | 90% 以上 |
| シフト最適化 | 85% 以上 |
| 請求・Zengin | 90% 以上 |
| セキュリティ | 95% 以上 |
| 全体 | 80% 以上 |

---

## 6. テスト実行コマンド

```bash
# 全テスト実行
python -m pytest tests/ -x -q

# 特定カテゴリのみ
python -m pytest tests/test_regression_auth.py -q
python -m pytest tests/test_regression_shift.py -q
python -m pytest tests/test_regression_billing.py -q
python -m pytest tests/test_regression_security.py -q

# リンタチェック
ruff check .

# カバレッジ測定
python -m pytest --cov=. --cov-report=term-missing tests/
```

---

## 7. 受け入れ基準

- [ ] 新規回帰テストファイル 4 つすべてがパスする
- [ ] 既存テストと整合し、回帰がないこと
- [ ] `ruff check .` がエラーゼロ
- [ ] カバレッジ 80% 以上（新規テスト追加後）
