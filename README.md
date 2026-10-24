# nusoft・open-hoikuict

<!-- READMEはnusoftプロジェクトの概要・現況・開発方針をまとめています -->

nusoftは、保育ICTプラットフォーム`open-hoikuict`をベースに、職員シフト自動作成・MFA・版管理の厳格化などの新機能を開発・統合するプロジェクトです。

> **注意: このREADMEは開発者向けの技術文書です。利用者向けガイドは `docs/features.md` や `docs/specifications.md` を参照してください。**
> 最終同期: 2026-10-22、`main` `d1e6bac` (Phase 3 シフト・MFA 実装完了)
> 本番・デモ環境は `docs/features.md`、仕様全体は `docs/specifications.md` を参照してください。

**[デモ環境](https://demo.hoikuict.net/) | [本番環境](https://open.hoikuict.net/) | [技術ガイド](docs/technical-guide.md) | [機能一覧](docs/features.md) | [導入手順](docs/getting-started.md) | [開発環境](docs/development.md)**

---

## 1. nusoft とは

**nusoft** は、`open-hoikuict` をベースに、**職員シフト自動作成 (nushift/shiftai)** や **多要素認証 (MFA)** 等の新機能を開発・統合するプロジェクトです。

| 項目 | 値 | 備考 |
| --- | --- | --- |
| リポジトリ | `open-hoikuict` | 本リポジトリ (mainブランチで開発) |
| 本番URL | `open.hoikuict.net` | 運用環境 |
| デモURL | `demo.hoikuict.net` | 検証用環境 |
| プロジェクト名 | **nusoft** | 派生開発の統合名 |
| 最新コミット | `d1e6bac` | Phase 3: シフト自動作成・MFA メールOTP 実装完了 |

### 由来・命名規則

1. **保育ICTの機能拡張**として、職員シフト最適化等の新領域を取り込む
2. **`nushift` との連携** — 別リポジトリ `annahoikuen-debug/nushift` (元 `shiftai`) を 2026-10-03 に取り込み。`nu-` 接頭辞で自リポジトリ機能として統合
3. **段階的リリース** — 既存機能を壊さず、機能フラグやモックで検証しながら本番投入

GitHub Organization / SNS ID は `nusoft` として統一予定。ドメイン・URL は既存を流用し、機能追加時にパスで区別。

---

## 2. 現況サマリ (2026-10-22 時点)

詳細は `docs/features.md` と `docs/specifications.md` を参照。

### 2.1 規模

| 指標 | 値 |
| --- | --- |
| Python ファイル数 (gen_bunnrei, vendor, venv 除く) | 316 |
| Python 総行数 | 85,197 |
| `models.py` | 2,688行 / class 175 |
| `routers/` 以下の Python ファイル | 38 |
| テストファイル数 | 100超 |
| `main.py` の `include_router` | 45 |

### 2.2 主要機能マトリクス

| 領域 | 実装状況 |
| --- | --- |
| 職員・児童台帳・請求 | 実装済み。CSV/Excel取込、職員ポータル、保護者連携、帳票出力 |
| 家庭・保護者アカウント | 実装済み。招待・紐付け・連絡先同期・停止/再開 (2026-09-23 統合済み) |
| 児童記録・保育要録 | 実装済み。観察ログ、訂正・無効化、設定版、児童票・進捗一覧 |
| 健康管理 | 実装済み。プロフィール、アレルギー、健診・グラフ。感染症・与薬は後続 |
| 保護者通知・プッシュ | 実装済み。Web Push、本番設定、配送・再試行・到達レポート |
| 請求・延長保育料金 | 実装済み。プレビュー、転送・再転送・解除、競合処理、監査 |
| 職員ポータル・権限 | 実装済み。ホーム、担当クラス、予定、要確認、タイムライン。集約権限・口座保護 |
| **職員シフト自動作成** | **基盤実装済み (Phase 3.1)。vendor/nushift/shiftai 取込・12 DBテーブル作成済み。プラン作成・求解ジョブ（CBCワーカー）・セル編集・ピン留め・承認ゲート（BLOCKER違反で承認ブロック）・配置割れギャップ検査・ステータスAPI 実装済み** |
| **多要素認証 (MFA)** | **実装済み (Phase 3.4)。メールOTP 対応。パスワード認証後、登録メールアドレスへ6桁コードを送信・検証してセッション発行。TOTPアプリ不要・DB変更最小限** |

### 2.3 仕様書・未実装一覧

| 領域 | 仕様書 | 状況 |
| --- | --- | --- |
| 施設設定 | `docs/facility-settings-spec.md` | 実装完了 (Phase 3.2、FacilitySettings・CSRF・管理画面) |
| 職員有給管理 | `docs/paid-leave-management-spec.md` | 実装完了 (Phase 3.3、有給台帳・申請承認・シフト希望休自動連携) |
| 一括データ移行 | `docs/beta-production-data-migration-spec.md` | 未実装。CSV対応は現行実装へ反映済み |
| 職員シフト自動作成 | `docs/shift-schedule-integration-proposal-2026-10-03.md` | 実装完了 (Phase 3.1、12テーブル・求解ワーカー・セル編集・承認ゲート・有給連携・配置割れギャップ検査) |
| MFA | `docs/local-authentication-spec.md` | 実装済み (Phase 3.4、メールOTP) |
| 児童記録・保育要録 | `docs/child-records-spec.md` | 実装完了 (Phase 2.1、独自項目UUIDキー・設定版楽観ロック・動的UI) |
| 健康管理レビュー | `docs/health-record-spec-review.md` | 進行中 |

### 2.4 技術的負債 (R01〜R08)

`docs/comprehensive-project-review-2026-09-05.md` の R01〜R08 は **Phase 1 で解消済み**。

| # | 課題 | 状況 |
| --- | --- | --- |
| R01 | お知らせの承認が確認した版に結び付いていない | 解消 (`Notice.lock_version`、`_claim_notice_lock`) |
| R02 | お知らせの配信対象の不正入力が `all` に広がる | 解消 (fail-closed 化) |
| R06a | 観察訂正の版チェックが fail-open | 解消 (`expected_updated_at` 必須化) |
| R06b | 不正な閲覧範囲を `all_staff` へ補正 | 解消 (fail-closed 化) |
| R06c | 独自項目の key が表示名に由来する | 解消 (`new_custom_field_key()` UUID 版) |
| R06d/e | 確定処理の所有者・書き込み経路の混在 | 解消 (所有者統一・移行経路分離) |
| R07 | 仕様書の現況が古い | 解消 (2026-10-05 実測で更新) |
| R08 | main・公開デモ・カーネル仕様に3本の枝 | 進行中 (main を正本に集約) |

`ruff check .` は **All checks passed**。CI (pytest / mkdocs strict) も緑。

---

## 3. 開発方針・フェーズ

`docs/comprehensive-project-review-2026-09-05.md` 以降の設計判断をまとめます。各フェーズの完了条件は「試験が通る・仕様書が揃う・CIが緑」です。

### Phase 0: nushift 取込 (完了)

- `vendor/nushift/shiftai` を取込 (`test_shiftai_vendor.py` で動作確認)
- `requirements.txt` に `pandas` / `numpy` / `pulp` 追加 (`pulp` は `<3` 固定)
- プレビュー画面 `tools/shift-schedule-preview/` 完成

### Phase 1: 負債解消・契約統一 (完了)

R06/R07 と R01/R02 の重要操作の契約を先に揃え、共通楽観ロックモジュール `common/optimistic_lock.py` を導入。

1. Ruff 3件の解消 — 完了
2. R02 お知らせの配信対象を fail-closed 化 — 完了
3. R01 お知らせの承認・差戻しを確認した版に結び付ける (`Notice.lock_version`) — 完了
4. R06a 観察訂正の版チェックを fail-closed 化 — 完了
5. R06b 児童記録の閲覧範囲を fail-closed 化 — 完了
6. R06c 独自項目の key を表示名から独立した安定IDへ — 完了
7. R06d/e 確定処理の所有者をそろえ、起動時の書き込みと移行の経路を分離 — 完了
8. R07 仕様書の現況更新 — 完了
9. R08 ブランチの整理 — 進行中

### Phase 2: 変更・更新サイクルを一巡させる (完了)

児童記録・お知らせ・健康管理の「作成→確認→確定→訂正→履歴」を一巡させ、版管理・権限・通知が矛盾なく回ることを確認。

**`AGENTS.md` の開発フロー規約に従い、機能単位で PR → 試験 → マージを徹底。** 機能の設計書 (`docs/specifications.md` 参照) に「完了の定義 (DoD)」を書き、フェーズ境界で DoD チェックリストを満たすこと。

### Phase 3: nusoft 固有機能の実装 (進行中)

`shift_schedule` を核に、職員中心の新機能を積み上げ。

| 機能 | 状況 | 依存 |
| --- | --- | --- |
| 職員シフト自動作成 | 基盤実装済み (Phase 3.1) | vendor取込済み・12 DBテーブル・求解ワーカー・セル編集・承認ゲート・ギャップ検査 |
| 施設設定 | 未実装 | `FacilitySettings` の画面・API |
| 有給管理 | 未実装 | `paid_leave` の申請・承認・残高・シフトと土台共用 |
| MFA (メールOTP) | 実装済み (Phase 3.4) | Argon2id 上に追加 |

**シフト実装の詳細（Phase 3.1）:**
- **DBテーブル 12 件**: `shift_facility_settings`, `shift_facility_closed_days`, `staff_qualifications`, `staff_contracts`, `staff_shift_preferences`, `staff_shift_unavailability`, `child_planned_arrival_defaults`, `shift_plans`, `shift_plan_cells`, `shift_solve_jobs`, `shift_violations`, `shift_planning_audits`
- **ルート**: `GET/POST /shifts/plans` (一覧・作成), `GET /shifts/plans/{id}` (詳細＋ギャップ警告), `POST /shifts/plans/{id}/solve` (求解ジョブ発行), `GET /shifts/plans/{id}/status` (求解状態API), `POST /shifts/plans/{id}/approve` (承認ゲート, BLOCKER違反で409), `POST /shifts/plans/{id}/cells` (セル編集・ピン留め)
- **求解ワーカー**: `ThreadPoolExecutor(max_workers=1)` で CBC を非同期実行。リクエスト経路では CBC 起動しない
- **承認ゲート**: BLOCKER 違反（1日10h超など）がある場合、承認を 409 でブロック
- **配置割れギャップ検査**: プラン詳細画面で最大 3 日分の配置割れをプレビュー表示

**シフトソルバ性能目安:**
- 計算単位は **週 (7日固定)**。月単位は不可
- `time_limit_sec` は上限ではない。リクエスト経路で CBC 起動禁止、専用ワーカー必須
- 「最適」ではなく「**実行可能**」と表示、`PARTIAL` も正常終了で保存
- 1日10h 超 = BLOCKER (労基法 32 条)、8h45m 超 = WARNING
- 承認は **園長のみ**。BLOCKER あれば 409
- 免責文言を 3 か所 (結果冒頭・確定ボタン・出力ファイル) に繰り返し

### Phase 4: AI・外部連携 (未着手)

外部 AI の判断を導入し、現場判断を補完。

- 文例生成・要約・翻訳を API 経由で提供 (SDK不要・プロンプトのみ)
- 児童記録の所見・計画文を AI で下書き・職員が修正
- 外部カレンダー・出退勤システムとの双方向同期 (CalDAV / 打刻 API)
- **人間-in-the-loop** を前提とし、AI 出力は「提案」扱い。最終承認は職員・施設長。

**実装の分離原則**: 業務ロジック (制約・スコア・状態遷移) は自前で実装し、AI は「文面生成・要約・分類」のみに使用。ベンダー依存は薄いアダプタ層で吸収。

---

## 4. 実装上の決定事項 (Architecture Decision Records)

| # | 決定事項 | 理由 |
| --- | --- | --- |
| I1 | 家庭・児童紐付けを **職員画面で一元管理** | `family_support.py:287` を参照 |
| I2 | 時刻扱いを `time_utils.local_today()` / `local_naive_now()` / `utc_now()` に統一 | `docs/development.md` |
| I3 | CSRF・多重送信防止を全 `POST` に適用 | セキュリティ要件 |
| I4 | 権限変更を **監査ログ必須** とする | 運用要件 |
| I5 | URL設計を **機能単位で統一** (`/plans/`, `/records/` 等) | `docs/documentation.md` |
| I6 | SQLite/PostgreSQL 両対応のマイグレーション | `docs/architecture.md` |
| I7 | 機能単位の UI プロトタイプ → 実装フロー | `docs/ui-prototype-workflow.md` |
| I8 | main ブランチを単一正本化 | R08 |
| I9 | 横断操作の版管理を統一 | 総合再評価 §6 |

---

## 5. 受入基準・合格ライン

CI と Docker の合格ラインは以下。Python 3.12、macOS / Linux / Windows PowerShell 対応。詳細は `docs/development.md`。

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
ruff check .
python -m pytest tests/ -x -q
python -m mkdocs build --strict
```

`http://127.0.0.1:8000/` で起動確認。デモデータ投入は `docs/demo-data.md`、環境プロファイルは `docs/environment-profiles.md`。

Windows で SQLite を使う場合、`HOIKUICT_ALLOW_UNMANAGED_SCHEMA=1` でスキーマ管理を緩和可能 (busy timeout 回避)。本番は PostgreSQL 推奨。

---

## 6. ドキュメント一覧

- [クイックスタート](docs/beta-quickstart.md) — Windows/Ubuntu 別インストール
- [日常業務ガイド](docs/daily-work.md) — 通知・出欠・記録の基本操作
- [アカウント管理](docs/accounts.md) — 保護者登録・職員招待
- [CSV 取込ガイド](docs/family-guardian-csv-guide.md) — 家庭・園児・職員 CSV
- [運用・バックアップ](docs/operations.md) — バックアップ/リストア・セキュリティ
- [画面遷移・URL 一覧](docs/screen-transition-list.md)
- [アーキテクチャ](docs/architecture.md)
- [変更履歴](docs/history.md)
- [ピロット導入仕様 v2](docs/pilot-deployment-spec-v2.md)
- [楽観的ロックパターン](docs/optimistic-lock-pattern.md)

ドキュメントプレビュー:

```bash
python -m mkdocs serve --dev-addr 127.0.0.1:8008
python -m mkdocs build --strict
```

`http://127.0.0.1:8008/` で確認。`mkdocs.yml` の nav 更新時は `docs/documentation.md` も参照。

---

## 7. ライセンス・貢献

[MIT License](LICENSE)。商用利用・改変・再配布自由。保証なし。

バグ報告・機能提案は [GitHub Issues](https://github.com/hoikuict/open-hoikuict/issues) または `openhoikuict@gmail.com` へ。[CONTRIBUTING.md](CONTRIBUTING.md) / [SUPPORT.md](SUPPORT.md) / [SECURITY.md](SECURITY.md) も参照。

---

## 8. 更新履歴 (Changelog)

### 未リリース (2026-10-22, `main` `d1e6bac`)
- **Phase 3.1**: 職員シフト自動作成基盤実装 (12 DBテーブル・求解ワーカー・セル編集・承認ゲート・配置割れギャップ検査・ステータスAPI)
- **Phase 3.4**: MFA メールOTP (多要素認証) 実装
- **README.md**: バージョン・フェーズ状況を Phase 3 まで反映、技術的負債 R01-R08 を解消済みに更新
- **docs/features.md**: シフト・MFA の実装状況を更新、未実装リストから削除
- **docs/specifications.md**: シフト・MFA の状況を「実装済み」に更新
- **docs/faq.md**: シフト・MFA に関する Q&A を追加

### nusoft v0.1.2 (2026-10-10)
- **README.md**: バージョン表記を v0.1.2 に更新、Phase 1 完了項目を反映
- **test_child_records.py**: 児童票作成テストで期間指定パラメータ追加、履歴表示アサーション修正
- **test_spec_changes_20260925.py**: 観察訂正テストに `expected_updated_at` 必須化対応
- **scripts/backup_contracts/monthly-library-20260927.json**: Notice.lock_version 列追加

### nusoft v0.1.1 (2026-10-05)
- **負債解消 (R01/R02/R06/R07/R08)**: fail-closed 化、楽観ロック (lock_version)、版チェック必須化
- **child_records/**: 閲覧範囲・独自項目key・訂正版チェックの厳格化
- **routers/notices.py**: 配信対象解析を fail-closed 化、承認/差戻しに rowcount ベース楽観ロック
- **database.py**: family/health bootstrap 移行関数化、extended_care_charges 監査列追加
- **docs/specifications.md**: 現況 2026-10-05 更新、新仕様書参照追加
- **tests**: 新仕様対応テスト追加 (lock_version、不正ID 422 等)

### nusoft v0.1 (2026-10-03)
- **職員シフト自動作成 (nushift/shiftai) 統合**: vendor 取込、依存追加、モック画面完成
- **mkdocs.yml**: 変更履歴にシフト提案書追加
- **requirements.txt**: pandas/numpy/pulp<3 追加
- **README-nusoft.md**: プロジェクト概要ドキュメント新規作成 (README.md に統合後削除)

---

*`main` `d1e6bac` を基準に 2026-10-22 に更新。nusoft は派生開発の統合名です。*