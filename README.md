# nusoft・open-hoikuict

<!-- READMEはnusoftプロジェクトの概要・現況・開発方針をまとめています -->

nusoftは、保育ICTプラットフォーム`open-hoikuict`の派生プロジェクトとして、職員シフト自動作成などの新機能を開発・統合するためのブランチです。

> **注意: このREADMEは開発者向けの技術文書です。利用者向けガイドは `docs/features.md` や `docs/specifications.md` を参照してください。**
> 最終同期: 2026-10-10、`main` `c9aeca5` (nusoft v0.1.1)
> 本番・デモ環境は `docs/features.md`、仕様全体は `docs/specifications.md` を参照してください。

**[デモ環境](https://demo.hoikuict.net/) | [本番環境](https://open.hoikuict.net/) | [技術ガイド](docs/technical-guide.md) | [機能一覧](docs/features.md) | [導入手順](docs/getting-started.md) | [開発環境](docs/development.md)**

---

## 1. nusoft とは

**nusoft** は、`open-hoikuict` をベースに、**職員シフト自動作成 (nushift/shiftai)** 等の新機能を開発・統合するための派生プロジェクトです。

| 項目 | 値 | 備考 |
| --- | --- | --- |
| リポジトリ | `open-hoikuict` | 本リポジトリ (mainブランチで開発) |
| 本番URL | `open.hoikuict.net` | 運用環境 |
| デモURL | `demo.hoikuict.net` | 検証用環境 |
| プロジェクト名 | **nusoft** | **派生開発の統合ブランチ名** |

### 由来・命名規則

1. **保育ICTの機能拡張**として、職員シフト最適化等の新領域を取り込む
2. **`nushift` との連携** — 別リポジトリ `annahoikuen-debug/nushift` (元 `shiftai`) を 2026-10-03 に取り込み。今後 `nu-` 接頭辞で自リポジトリ機能として統合予定
3. **段階的リリース** — 既存機能を壊さず、機能フラグやモックで検証しながら本番投入

GitHub Organization / SNS ID は `nusoft` として統一予定。ドメイン・URL は既存を流用し、機能追加時にパスで区別。

---

## 2. 現況サマリ (2026-10-10 時点)

詳細は `docs/features.md` (2026-09-13 以降の差分) と `docs/specifications.md` を参照。

### 2.1 規模

| 指標 | 値 |
| --- | --- |
| Python ファイル数 (gen_bunnrei, vendor, venv 除く) | 316 |
| Python 総行数 | 85,197 |
| HTML テンプレート行数 | 約19,500 / 6,703行 |
| `models.py` | 2,688行 / class 175 |
| `routers/` 以下の Python ファイル | 38 |
| テストファイル数 | 100超 (models 99 + tests 1超) |
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
| **職員シフト自動作成** | **計画・vendor取込済み (2026-10-03)。配置基準リンク型 MILP (shiftai)。画面・ルート未実装 (モック完了・試用待ち)** |

### 2.3 仕様書・未実装一覧

| 領域 | 仕様書 | 状況 |
| --- | --- | --- |
| 施設設定 | `docs/facility-settings-spec.md` | 未実装。シフト用 `shift_facility_settings` は独立実装予定 |
| 職員有給管理 | `docs/paid-leave-management-spec.md` | 未実装。シフトと土台共用可 |
| 一括データ移行 | `docs/beta-production-data-migration-spec.md` | 未実装。CSV対応は現行実装へ反映済み |
| MFA (TOTP) | `docs/local-authentication-spec.md` | 未実装。Argon2id の上に追加 |
| **職員シフト自動作成** | `docs/shift-schedule-integration-proposal-2026-10-03.md` | **vendor取込済み。画面・ルート未実装** |
| 児童記録・保育要録 | `docs/child-records-spec.md` | 進行中 |
| 健康管理レビュー | `docs/health-record-spec-review.md` | 進行中 |

### 2.4 技術的負債 (R01〜R08)

`docs/comprehensive-project-review-2026-09-05.md` の R01〜R09 のうち、コードに残っているものです。
出典の行番号は **2026-10-05 にコードを再調査した結果**です。

| # | 課題 | 影響 | 出典 (2026-10-05 実測) |
| --- | --- | --- | --- |
| R01 | お知らせの承認が確認した版に結び付いていない | 古い画面からの承認で、変更後の本文が公開され得る | `routers/notices.py:601` (`approve_notice` が状態しか見ない) |
| R02 | お知らせの配信対象の不正入力が `all` に広がる | 限定した対象が、意図より広く公開され得る | `routers/notices.py:113-162` (`_upsert_targets`)、`:501-504` |
| R06a | 観察訂正の版チェックが fail-open | フィールドを欠落させれば検査を迂回できる | `child_records/router.py:769` |
| R06b | 不正な閲覧範囲を `all_staff` へ補正する | 不正値が広い閲覧権限として有効になる | `child_records/access.py:26-27`、`child_records/router.py:202-206` |
| R06c | 独自項目の key が表示名に由来する | 名称変更を同一項目として追跡しにくい | `child_records/settings.py:206` (`custom_field_key`) |
| R06d | 確定処理の所有者が Router／Repository／service で異なる | 複数処理の取消境界が不明確 | `child_records/router.py:786-791` (Router が直接更新)、`:136-159` (記録作成が設定版を書く) |
| R06e | 起動・初回参照で旧データを補正する | 通常利用とデータ移行の書き込み経路が混在する | `main.py:102-103`、`database.py:1315-1325` |
| R07 | 仕様書の現況が古い | 設計判断の材料が誤る | `docs/specifications.md:3` (現況確認 2026-09-17 のまま) |
| R08 | main・公開デモ・カーネル仕様に3本の枝 | 3系統を長く育てる運用になる | R08 |

**解消済み (2026-10-05 実測)**: 「Ruff の未使用3件」は `1cc7dc8` で解消済みです。
`ruff check .` は 351 ファイル対象で **All checks passed** (`extended_care_billing_transfer_service.py` と `routers/extended_care_fees.py` の未使用バインド3件を削除)。R01〜R08 の記載はコードを再調査した結果で更新しています。

---

## 3. 開発方針・フェーズ

`docs/comprehensive-project-review-2026-09-05.md` 以降の設計判断をまとめます。各フェーズの完了条件は「試験が通る・仕様書が揃う・CIが緑」です。

### Phase 0: nushift 取込 (2026-10-03 完了)

- `vendor/nushift/shiftai` をサブモジュール的に取込 (`test_shiftai_vendor.py` で動作確認)
- `requirements.txt` に `pandas` / `numpy` / `pulp` 追加 (`pulp` は `<3` 固定)
- `mkdocs.yml` の nav にシフト提案書追加
- プレビュー画面 `tools/shift-schedule-preview/` 完成 (約44画面、BC螳溯後退・隠蔽完了)

### Phase 1: 負債解消・契約統一 (最優先・即着手)

R06/R07 と R01/R02 の **重要操作の契約** を先に揃えます。再利用できる実装は `plan_docs/store.py:574` の `_claim_lock` (原子的 UPDATE + rowcount 検査) と `institutional_record_service.py:384` の原子的更新です。

1. **Ruff 3件の解消 — 完了 (`1cc7dc8`)。** `ruff check .` は通る。構造課題と同一視しない
2. **R02** お知らせの配信対象を fail-closed 化 (不正入力を `all` に広げない) — **完了 (v0.1.1)**
3. **R01** お知らせの承認・差戻しを確認した版に結び付ける (`Notice.lock_version`) — **完了 (v0.1.1)**
4. **R06a** 観察訂正の版チェックを fail-closed 化 (`expected_updated_at` 欠落で通過させない) — **完了 (v0.1.1)**
5. **R06b** 児童記録の閲覧範囲を fail-closed 化 (不正値を `all_staff` にしない) — **完了 (v0.1.1)**
6. **R06c** 独自項目の key を表示名から独立した安定IDへ — **完了 (v0.1.1)**
7. **R06d/e** 確定処理の所有者をそろえ、起動時の書き込みと移行の経路を分離
8. **R07** 仕様書の現況更新 (古い「未実装」を現行コードに合わせる)
9. **R08** ブランチの整理 (main を正本として維持。公開デモ・一般修正は目的ごとに選び、試験を伴って戻す)

### Phase 2: 変更・更新サイクルを一巡させる (中核・最重要)

児童記録・お知らせ・健康管理の「作成→確認→確定→訂正→履歴」を一巡させ、版管理・権限・通知が矛盾なく回ることを確認。

| 手順 | 内容 | 完了基準 |
| --- | --- | --- |
| 1 | 記録SHA・訂正 runtime 統合 | 記録ID・版・隠蔽ルールが runtime 依存 |
| 2 | 閲覧範囲の安定ID化 | 隠蔽ルールA/B の確定・差戻しが版ベース |
| 3 | 版ベースの通知・公開制御 | 通知文面・対象が版に結び付く |
| 4 | 対象単位の再試行・到達可視化 | 到達ログ単位で再送・障害検知 |
| 5 | 一巡試験の自動化 | 観察→訂正→通知→確認 が CI で回る |

**`AGENTS.md` の開発フロー規約に従い、機能単位で PR → 試験 → マージを徹底。** 機能の設計書 (`docs/specifications.md` 参照) に「完了の定義 (DoD)」を書き、フェーズ境界で DoD チェックリストを満たすこと。

### Phase 3: nusoft 固有機能の実装

`shift_schedule` を核に、職員中心の新機能を積み上げ。

| 機能 | 状況 | 依存 |
| --- | --- | --- |
| 職員シフト自動作成 | `vendor/nushift/shiftai` (MILP・CBC) | vendor取込済み・仕様確定待ち |
| 施設設定 | `FacilitySettings` の画面・API | 未実装 |
| 有給管理 | `paid_leave` の申請・承認・残高 | 未実装・シフトと土台共用 |
| MFA | Argon2id 上に TOTP 追加 | 未実装 |

**シフトソルバ性能目安 (vendor/nushift/shiftai 2026.2.14 時点):**

- **職員30名・30日・制約200** で **30秒以内** (上限 46.7秒・中央値 4.5秒)
- `time_limit_sec` は **無制限 (0)** — 0秒指定で CBC が最適解まで探索
- 解なし時は **部分解を返さず `failed`** とする
- 1-10職員: **BLOCKER 0件・WARNING 1件** → 2職員以上で BLOCKER 45件 → WARNING → BLOCKER が増大
- 管理者 (`staff_role=admin`) 以外が LOCKER を持つ操作は 409 で拒否
- 解の根拠を **職員単位で可視化** — 担当児童・配置基準・希望休の寄与度を UI で提示

> 現場の職員シフト作成負担 (月40-60時間) を「配置基準・希望休・資格の充足」という **数理最適化問題** に帰着させ、AI に「解の説明」をさせる構成。
> 保育士の「勤務表作成」から「解の妥当性判断」へシフトし、施設長の承認フローを「制約・スコア・代替案」の三点セットで完結させる。

### Phase 4: AI・外部連携

外部 AI の判断を導入し、現場判断を補完。

- 文例生成・要約・翻訳を API 経由で提供 (SDK不要・プロンプトのみ)
- 児童記録の所見・計画文を AI で下書き・職員が修正
- 外部カレンダー・出退勤システムとの双方向同期 (CalDAV / 打刻 API)
- **人間-in-the-loop** を前提とし、AI 出力は「提案」扱い。最終承認は職員・施設長。

**実装の分離原則**: 業務ロジック (制約・スコア・状態遷移) は自前で実装し、AI は「文面生成・要約・分類」のみに使用。ベンダー依存 (OpenAI / Anthropic / I Gateway 等) は薄いアダプタ層で吸収。

---

## 4. 実装上の決定事項 (Architecture Decision Records)

| # | 決定事項 | 理由 |
| --- | --- | --- |
| I1 | 家庭・児童紐付けを **職員画面で一元管理** | 運用実態に合わせ `family_support.py:287` を参照 |
| I2 | 時刻扱いを `time_utils.local_today()` / `local_naive_now()` / `utc_now()` に統一 | `docs/development.md` |
| I3 | CSRF・多重送信防止を全 `POST` に適用 | セキュリティ要件 |
| I4 | 権限変更を **監査ログ必須** とする | 運用要件 |
| I5 | URL設計を **機能単位で統一** (`/plans/`, `/records/` 等) | `docs/documentation.md` |
| I6 | SQLite/PostgreSQL 両対応のマイグレーション | `docs/architecture.md` |
| I7 | 機能単位の UI プロトタイプ → 実装フロー | `docs/ui-prototype-workflow.md` |
| I8 | main ブランチを単一正本化 | R08 |
| I9 | 横断操作の版管理を統一 (店舗・担当・権限) | 邱丞粋蜀崎ｩ穂ｾ｡ 6. |

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
- **README-nusoft.md**: プロジェクト概要ドキュメント新規作成

---

*`main` `c9aeca5` 以降の変更を含む。nusoft は派生開発の統合ブランチとして運用。*