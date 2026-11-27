# 商用リリースに向けた 9大改善 詳細実装計画書

- **作成日**: 2026-11-27
- **根拠データ**: [dense_multi_persona_quick_report.md](file:///c:/Users/user/openict/simulation_3months/dense_multi_persona_quick_report.md)（v5.0 並行シミュレーション: `workers=4, parallel_all=True, security_probes=True, conflict_probes=True`）
- **対象システム**: `open-hoikuict`（FastAPI + SQLModel + Jinja2/Tailwind）および `simulation_3months`

---

## 0. エグゼクティブサマリ・フェーズ計画

シミュレーション結果から抽出した「コード・業務効率化・UI/UX・使い勝手・見た目」の 9 つの改善を、商用リリースへの重要度順に 3 フェーズで実装します。

| Phase | 優先度 | 対象施策 | ゴール |
| :--- | :--- | :--- | :--- |
| **Phase 1** | **P0（ブロッカー解消）** | **#1** 請求確定連動 / **#4** 競合解消UX / **#9** マイグレーションCI | Release Gate の `FAIL` 項目（全銀スキップ・競合エラー30件）をゼロ化し、DB破壊を防ぐ |
| **Phase 2** | **P1（業務効率化・性能）** | **#2** 延長保育一括確認 / **#5** 看護師画面高速化 / **#7** 担任HUD最適化 | 現場のクリック数・待ち時間（580.8 ms → 150 ms 未満）を大幅削減 |
| **Phase 3** | **P2（UX・見た目向上）** | **#3** 月末締めステッパー / **#6** 保護者1画面統合 / **#8** NuShift差分UI | 操作迷子ゼロ・片手操作・視覚的安心感を実現 |

---

## Phase 1: リリースブロッカー解消・基盤信頼性（P0）

### #1. 請求サイクル確定と `billing_claims` のワンストップ連動
- **背景**: シミュレーションで `POST /extended-care-fees/billing-transfer` 後に `POST /billing/cycles/{cycle_id}/confirm` を実行したところ、`billing_cycles` は `confirmed` になる一方、配下の `billing_claims` 84件が `draft` のまま残り、3ヶ月すべて全銀出力（`can_export`）がブロックされた。
- **対象ファイル**:
  - [routers/billing.py](file:///c:/Users/user/openict/open-hoikuict/routers/billing.py)（`confirm_cycle` L1547 付近）
  - `templates/billing/` 配下の請求サイクル管理画面
- **実装詳細**:
  1. `confirm_cycle(cycle_id)` 内で `cycle.status = BillingCycleStatus.confirmed` に更新する際、同じ `billing_cycle_id` に紐づく `BillingClaim` のうち `status == BillingClaimStatus.draft` かつ `total_amount > 0`（または対象外でないもの）を一括で `BillingClaimStatus.confirmed` に更新する（`confirmed_at` / `confirmed_by` / `updated_at` も記録）。
  2. `unconfirm_cycle` 時は、未出力（`status == confirmed`）の `BillingClaim` を `draft` に戻す（`exported` / `paid` が存在する場合は既存ガード通り拒否）。
  3. **監査ログ**: 一括昇格した `claims` 件数を監査ログおよびレスポンス JSON（`{"id": cycle.id, "status": "confirmed", "confirmed_claims_count": count}`）に含める。
- **受け入れ基準**:
  - シミュレーションで直SQLバイパスなしに 3ヶ月分の全銀出力・120バイト固定長・DB合計金額一致検算がすべて `PASS` すること。

---

### #4. お迎え申告の同時更新コンフリクト解消 UI & 409 正常化
- **背景**: `--conflict-probes`（同一園児・同一 `revision` への同時 POST）で、期待ステータス `{200, 302, 303, 409}` 以外の応答が 30 件発生した。
- **対象ファイル**:
  - `routers/parent_portal/`（お迎え予定登録・更新ハンドラ）
  - `templates/parent_portal/`（お迎え申告フォームテンプレート）
- **実装詳細**:
  1. **バックエンド**: まずシミュレーションで検出された 30 件の実際の HTTP ステータス（SQLite ロックによる 500、あるいは 422 等）を特定・修正する。`revision` 不一致時は確実に `409 Conflict`（HTML フォーム送信時は最新の `revision` と相手方の更新内容をコンテキストに渡した 409 テンプレート、Fetch/API 時は JSON）を返す。SQLite の `OperationalError("database is locked")` に対しては短い指数バックオフリトライまたはトランザクション範囲縮小を適用する。
  2. **フロントエンド（UI/UX）**: `409` 発生時は「直前にご家族（〇〇さん）が `18:10` に変更しました」という比較バナーを表示し、「最新内容を読み込む」「自分の内容（`17:40`）で上書き確定する」の 2 択ボタンを提示する。
- **受け入れ基準**:
  - `--conflict-probes` で 5xx が 0 件、かつ `409` または正常更新として安全にハンドリングされること。

---

### #9. マイグレーション追記禁止 CI と起動前 DB ヘルスチェック
- **背景**: 完了済みマイグレーション `048` への後付け追記により `board_qr_enabled` 列欠落の 500 エラーが発生。また `--reset` 時の参照不整合により `_validate_sqlite_foreign_keys()` で起動停止した。
- **対象ファイル**:
  - [db_migrations/sqlite_legacy.py](file:///c:/Users/user/openict/open-hoikuict/db_migrations/sqlite_legacy.py)
  - `tests/`（マイグレーション検証テスト新設）
  - [dense_multi_persona_engine.py](file:///c:/Users/user/openict/simulation_3months/dense_multi_persona_engine.py)（実装済み）
- **実装詳細**:
  1. **CI テスト追加**: 新規テスト `tests/test_migrations_integrity.py` を作成し、以下を自動検証する。
     - 全 SQLModel テーブルの全カラムが、空 DB へ `create_db_and_tables()` 実行後の実テーブルに存在すること。
     - `048` 以前の履歴状態から最新マイグレーションを適用しても不足カラムが残らないこと。
     - `PRAGMA foreign_key_check` が空配列であること。
  2. **運用ルール化**: ドキュメントに「既存マイグレーション関数へのカラム追記禁止（必ず新しい連番エントリを追加）」を明記する。
- **受け入れ基準**:
  - `pytest tests/test_migrations_integrity.py` が常に PASS すること。

---

## Phase 2: 業務効率化・パフォーマンス改善（P1）

### #2. 延長保育料「クラス別・一括確認」API と UI（旧「案7」実現）
- **背景**: 1ヶ月あたり 439〜550 件（3ヶ月計 1,441 件）の延長保育料を単件 POST で確定しており、画面からの運用負荷が極めて高い。
- **対象ファイル**:
  - [routers/extended_care_fees.py](file:///c:/Users/user/openict/open-hoikuict/routers/extended_care_fees.py)
  - [templates/extended_care_fees/list.html](file:///c:/Users/user/openict/open-hoikuict/templates/extended_care_fees/list.html)
- **実装詳細**:
  1. **バックエンド**: `POST /extended-care-fees/bulk-confirm` を新設。
     - パラメータ: `month`（必須）、`classroom_id`（任意：未指定なら全クラス）、`exclude_anomalies`（既定 `True`：未打刻・手動修正中等の要個別精査を除外）。
     - 認可: `require_can_edit`（または管理者/請求担当権限）。
     - 監査ログ: 一括確定件数・対象月・実行者を記録。
  2. **フロントエンド（UI/見た目）**: `list.html` 上部に「表示中の正常明細を一括確定（〇〇件）」ボタンを配置し、確認モーダルで件数と合計金額をプレビューしてから確定できるようにする。要個別確認（異常値あり）はアンバー背景で残し、人間の判断が必要なものだけに集中させる。
- **受け入れ基準**:
  - シミュレーションの `confirm_month_charges` が 550 リクエスト → 1 リクエストに短縮され、異常明細が誤って確定されないこと。

---

### #5. 看護師「健康ダッシュボード」の高速化とトリアージ表示
- **背景**: シミュレーションで他ペルソナが 6〜136 ms 台なのに対し、看護師の `GET /health` だけ平均 **580.8 ms** と突出して遅かった。
- **対象ファイル**:
  - [routers/child_health.py](file:///c:/Users/user/openict/open-hoikuict/routers/child_health.py)
  - `templates/health/` 配下のダッシュボードテンプレート
- **実装詳細**:
  1. **クエリ最適化（バックエンド）**:
     - 全期間の履歴を毎回全件結合せず、初期表示は「当日（または直近48時間）の異常・要対応レコード」と「クラス別検温完了率サマリ（SQL `GROUP BY` 集計）」のみを取得する。
     - 過去履歴一覧はページネーション（25件/ページ）またはタブ選択時の非同期取得（`/health/history`）へ分離する。
  2. **UI/見た目**: 画面最上部に **トリアージ・カード** を配置し、緊急度別に色分けする（赤：`37.5℃以上`・感染症疑い／黄：投薬依頼あり・要経過観察／緑：異常なし）。
- **受け入れ基準**:
  - シミュレーション上の看護師 `GET /health` 平均応答時間が **150 ms 以下**（現状比 70%以上短縮）になること。

---

### #7. クラス担任向け「未対応ピン留め」＆タブレット最適化 HUD
- **背景**: 担任6名は15日間で 3,320 リクエストを処理。園児100名規模では通常行に埋もれて「未打刻・発熱連絡・未確認」を見落とすリスクがある。
- **対象ファイル**:
  - [routers/attendance_checks.py](file:///c:/Users/user/openict/open-hoikuict/routers/attendance_checks.py)
  - `templates/attendance_checks/`
- **実装詳細**:
  1. **並び替えとフィルタ**: デフォルトのソート順を「①発熱・欠席連絡あり（未確認） → ②お迎え時刻変更あり → ③未登園 → ④登園済み」とし、「未対応のみ表示」トグルスイッチをヘッダに常設する。
  2. **見た目（タブレットHUD）**: 行間を広め（最低タップ領域 44×44px 以上）に取り、ステータスバッジ（「発熱 38.2℃」「延長 18:30」等）をアイコン＋ハイコントラスト色にして、保育中にタブレットをチラ見するだけで把握できるようにする。

---

## Phase 3: UX・見た目・現場満足度の最大化（P2）

### #3. 月末締め〜全銀出力の「ステッパー（進行ウィザード）」UI
- **背景**: 月末締めが `/extended-care-fees/` と `/billing/` に分断され、作業順序が分かりにくい。
- **対象ファイル**:
  - `templates/billing/` および `templates/extended_care_fees/` の共通ヘッダパーシャル
  - [routers/billing.py](file:///c:/Users/user/openict/open-hoikuict/routers/billing.py)（進捗状態算出ヘルパー）
- **実装詳細**:
  1. 対象月の状態をサーバー側で 5 段階（`1.再計算` → `2.延長料確定` → `3.請求転送` → `4.請求確定` → `5.全銀作成`）で評価する共通パーシャル `_closing_stepper.html` を作成。
  2. 各ステップに「完了（緑チェック）」「作業中・要対応残（アンバー数字バッジ）」「未着手（グレー）」を表示し、クリックで該当アクション／画面へ直接ジャンプできるようにする。

---

### #6. 保護者朝の連絡帳「1画面統合＆昨朝コピー」UX
- **背景**: 朝の登園ラッシュ時に 84世帯が「連絡帳」と「お迎え申告」の 2 画面を行き来して投稿している。
- **対象ファイル**:
  - `routers/parent_portal/`
  - `templates/parent_portal/`（連絡帳投稿フォーム）
- **実装詳細**:
  1. 連絡帳フォームの下部に「本日のお迎え予定（時刻・お迎え者）」セクションを折りたたみ／統合配置し、1回の送信で連絡帳＋お迎え予定を原子的に保存できるようにする。
  2. 「昨日の内容（睡眠・朝食・お迎え予定）をコピー」ボタンをフォーム上部に配置し、変更点（体温・連絡事項）だけ入力すれば **3タップ・15秒以内** で完了する UX にする。
  3. 選択肢（機嫌・朝食・排便等）をテキスト入力や小さなラジオボタンではなく、スマホで押しやすい大きめのピル型チップボタンに変更する。

---

### #8. 突発欠勤リペア（NuShift）の進行表示＆差分ハイライト UI
- **背景**: 1/6 インフルエンザ突発欠勤リペアの計算・同期に約 10.4 秒（`10,373 ms`）かかっており、処理中の無反応が現場の不安につながる。
- **対象ファイル**:
  - `shift_schedule/routers/` および `templates/shift_schedule/`
- **実装詳細**:
  1. リペア実行ボタン押下時に即座にプログレスモーダルを表示（「欠勤影響を分析中 → 基準充足を計算中 → 代替シフトを最適化中…」の疑似ステップ＋経過秒数表示）。
  2. 完了後はそのまま確定せず、**変更が入った職員・時間帯のセルだけをハイライトした Before / After 差分テーブル** を表示し、「この内容で反映＆対象職員へ通知」ボタンで確定する 2 ステップにする。

---

## 検証・リリース判定計画（Verification Plan）

各 Phase 完了ごとに以下を実行し、最終リリース判定を行います。

1. **自動テスト**: `pytest` によるマイグレーション整合性・請求確定連動・一括確認・409競合テストのパス。
2. **シミュレーション Release Gate（最終基準）**:
   ```powershell
   python c:\Users\user\openict\simulation_3months\dense_multi_persona_engine.py `
     --mode full --seed 42 --workers 8 --parallel-all `
     --security-probes --conflict-probes --reset --reset-billing
   ```
   - 予期しない失敗・HTTP/HTMLエラー: **0 件**
   - 認可境界（RBAC/IDOR）突破: **0 件**
   - 全銀フォーマット（120B・CP932）・DB請求金額突合: **3ヶ月すべて一致（PASS）**
   - 応答性能: **p95 < 500 ms / p99 < 1,500 ms**（看護師 `/health` 平均 **< 150 ms**）
