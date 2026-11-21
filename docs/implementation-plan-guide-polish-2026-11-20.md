# 実装計画書: ガイド機能の仕上げ・整合（Wave G）

- 日付: 2026-11-20
- 参照元: 今後の方向性提案 ①「仕上げ・整合（低コスト・スキーマ変更なし）」
- 関連計画:
  - `docs/implementation-plan-codmon-pain-point-improvements-2026-11-16.md`（Wave A〜F・P1-1/P1-2/P1-3 の実装元）
  - `docs/codmon-pain-point-improvement-proposals-2026-11-16.md`（改善提案書）
- ステータス: **計画（未実装）**
- 対象リポジトリ: `open-hoikuict`（FastAPI + Jinja2 + htmx + Tailwind / SQLModel + SQLite / pytest + ruff）
- 前提: Wave E にて `templates/shared/context_help.html`、`static/js/onboarding-tour.js` 8ステップ化・`UserOnboardingState` 永続化が実装済み。さらに 2026-11-20 に `templates/base.html` のツアー対象 8 箇所（`data-tour-step="1"`〜`"8"`）がすべて実在するよう修正済み（ステップ5 `/plans/`、6 `/shifts/`、7 `/billing/`、8 `/settings` を追加）。

---

## 1. 背景と目的

P1-1〜P1-3（設定ヘルスチェック診断・8ステップツアー・文脈ヘルプ）は実装済みだが、以下のずれが残っている。

1. **文脈ヘルプの配備が 2 画面のみ**（連絡帳一覧・設定診断）。MANUAL.md は「登降園管理、連絡帳、指導案、請求設定などの主要画面」と記載しており、記載と実態が不一致。
2. **MANUAL.md のツアー永続化の記述が実装と不一致**。`users.tour_progress`（JSON・ステップ単位）とあるが、実態は `user_onboarding_states` テーブルの `is_completed` / `completed_at` のみ。
3. **ツアーの進捗が利用者から見えない**。設定画面には「ツアーを開始」ボタンがあるだけで、完了/未完了・どこまで進んだかが分からない。

本ウェーブでは**スキーマ変更なし**で上記 3 点を解消し、ガイド機能を「実装と記載が一致した完成形」にする。

## 2. スコープと非スコープ

### 2.1 スコープ（3 タスク）

| ID | 区分 | タスク | スキーマ | 難易度 |
|---|---|---|---|---|
| G-1 | ガイド | 文脈ヘルプの配備拡大（4 画面追加・計 6 画面） | なし | 低 |
| G-2 | ガイド | ツアー進捗の可視化（設定トップに X/8 表示＋続きから再開） | なし（localStorage） | 低〜中 |
| G-3 | ドキュメント | MANUAL.md・README.md の記載整合 | なし | 低 |

### 2.2 非スコープ（本計画でやらないこと）

- ステップ単位のサーバ永続化（`tour_progress` JSON 化）→ 提案 ③。将来 `UserOnboardingState.progress`（JSON列）追加時に localStorage から移行する。
- ロール別ツアー内容 → 提案 ③。
- ヘルスチェックの項目別スコア化・診断履歴・自動診断 → 提案 ②。
- `?` キー（I1 ヘルプモーダル）からの文脈ヘルプ呼び出し統合 → 将来課題（P1-3 提案時点の未確定事項）。
- 保護者ポータル側への文脈ヘルプ配備（本計画は職員画面のみ）。

## 3. G-1: 文脈ヘルプの配備拡大

### 3.1 対象画面とヘルプ内容（確定案）

共通コンポーネント `templates/shared/context_help.html` を、既存 2 画面と同一の `{% with %}` パターンで 4 画面に追加する。いずれも `base.html` 継承画面であり、**ページヘッダー（`<h1>` ブロック）直後・最初のセクション/カードの前**に配置する（既存 2 画面と同一規則）。

| # | 画面 | テンプレート | ルート | `help_id` |
|---|---|---|---|---|
| 1 | 出欠一覧 | `templates/attendance_list.html` | `GET /attendance`（`routers/attendance.py:694`） | `help-attendance-list` |
| 2 | 請求設定 | `templates/billing/settings.html` | `GET /billing/settings`（`routers/billing.py:1440`） | `help-billing-settings` |
| 3 | 指導計画 | `templates/plan_docs/home.html` | `GET /plans/`（`plan_docs/routers/home.py:57`） | `help-plan-docs-home` |
| 4 | 施設設定 | `templates/facility_settings/index.html` | `GET /settings/facility`（`routers/facility_settings.py:55`） | `help-facility-settings` |

### 3.2 ヘルプ文言（ドラフト）

実装時に各画面の実際の機能と照合して微調整する。ステップは 3 つ・留意点は 2 つを基本形とする（既存 2 画面と同一構成）。

**出欠一覧**（`help-attendance-list`）

- steps:
  1. 当日の出欠確認 — 「クラス・日付で絞り込み、登園・降園・未登園・欠席を一覧で確認します。」
  2. 一括打刻・訂正 — 「複数園児の選択一括打刻や、打刻間違いの訂正申請をここから行えます。」
  3. お迎え予定の確認 — 「保護者ポータルから届いたお迎え予定時刻・お迎え者の変更を確認します。」
- cautions:
  - 「打刻の訂正は履歴が残ります。勝手な上書きではなく訂正機能を使ってください。」
  - 「欠席・遅刻の連絡は保護者ポータルから届きます。未確認の連絡がないか毎朝確認してください。」

**請求設定**（`help-billing-settings`）

- steps:
  1. 料金項目マスタ — 「給食費・教材費など毎月の請求項目（FeeItem）を登録・編集します。」
  2. 全銀口座振替設定 — 「委託者コード・引落口座など、銀行提出用電文の元になる情報を管理します。」
  3. 減免・多子軽減 — 「園児ごとの免除・減額と、兄弟割引の自動判定結果を確認できます。」
- cautions:
  - 「委託者コードが初期値（ダミー）のままでは全銀電文が銀行でエラーになります。」
  - 「設定変更は保存以降の請求に適用されます。確定済み請求は自動では変更されません。」

**指導計画**（`help-plan-docs-home`）

- steps:
  1. 日案・月案の作成 — 「クラスごとの日案・月案を作成します。前日振り返りを引用して下書きを素早く作れます。」
  2. 文例・AIサジェスト — 「定型文例の挿入や AI 候補生成で記入負担を減らします。」
  3. 印刷・PDF出力 — 「A4 帳票 PDF や印刷プレビューで、提出用のレイアウトを事前確認できます。」
- cautions:
  - 「添付した図表（環境構成図等）は PDF 帳票に自動で焼き込まれます。」
  - 「印刷・提出前にプレビューで改ページ位置を確認してください。」

**施設設定**（`help-facility-settings`）

- steps:
  1. お迎え最終時刻 — 「保護者キオスクで選べるお迎え予定時刻の上限を設定します。」
  2. 補食判定・補食費 — 「この時刻以降のお迎え予定を補食必要と初期判定し、注記に表示する金額を設定します。」
  3. 変更履歴 — 「過去 20 件の設定変更（誰が・いつ・何を）を確認できます。」
- cautions:
  - 「変更は保存以降のキオスク表示と補食判定に適用されます。過去の打刻・確定済み請求は変わりません。」
  - 「補食費など料金に関わる値は変更履歴に記録されます。」

### 3.3 実装イメージ（各テンプレート共通）

```jinja
<!-- G-1: 文脈ヘルプ -->
{% with help_id="help-attendance-list", help_title="出欠一覧の使い方と朝の業務の流れ", help_steps=[
  {"title": "当日の出欠確認", "desc": "…"},
  {"title": "一括打刻・訂正", "desc": "…"},
  {"title": "お迎え予定の確認", "desc": "…"}
], help_cautions=[
  "…", "…"
] %}
{% include "shared/context_help.html" %}
{% endwith %}
```

コンポーネント本体・CSS は変更しない（`help_steps|length` が 3 の場合、既存の `md:grid-cols-3` 相当のグリッドに乗る。`context_help.html:18` の分岐は「4 以下ならその個数、5 以上なら 3」であるため 3 項目で問題なし）。

## 4. G-2: ツアー進捗の可視化

### 4.1 仕様

設定トップ（`GET /settings`、`templates/settings/index.html`）の「ヘルプとガイド」セクションのツアー行を拡張する。

| 状態 | 表示 | 操作 |
|---|---|---|
| サーバ未完了 & 進捗あり | 「未完了・進捗 X/8」（X = localStorage の到達ステップ） | 「続きから再開」ボタン → X ステップ目からツアー開始 |
| サーバ未完了 & 進捗なし | 「未完了」（X = 0） | 「ツアーを開始」→ 1 ステップ目から |
| サーバ完了済み | 「完了済み」 | 「もう一度見る」（現行どおり最初から） |

- サーバ状態の取得は既存 `GET /settings/tour/status`（`routers/settings.py:178`）を再利用する。**API 変更なし**。
- 進捗 X は **localStorage**（`hoikuict_onboarding_progress` = 最後に表示したステップ番号 1〜8）を持つ。DB へは保存しない（ステップ単位のサーバ永続化は提案 ③ に譲る）。
- サーバ完了状態を優先する: 別端末で完了済みの場合、localStorage の進捗があっても「完了済み」表示にする。

### 4.2 JS 変更（`static/js/onboarding-tour.js`）

1. 定数追加: `var PROGRESS_KEY = "hoikuict_onboarding_progress";`
2. `showStep(idx)` 内で `try { localStorage.setItem(PROGRESS_KEY, String(idx + 1)); } catch (e) {}` を追加（ツアー表示中のみ書き込む）。
3. `restartOnboardingTour(startStep)` に引数を追加（省略時 0）。数値でなければ 0 にクランプ。
4. 新規公開関数:
   ```js
   window.startOnboardingTourFrom = function (stepIdx) { ... }
   // createTourElements() → showStep(clamp(stepIdx))
   ```
5. 新規ウィジェット初期化: `DOMContentLoaded` 時、ツアー自動起動の判定（現行: `#staff-sidebar` あり & ホーム画面のみ）とは**独立に**、`#tour-progress-label` が存在するページで:
   - `fetch("/settings/tour/status?tour_key=staff_console_tour")`（失敗時は何もしない＝現行表示のまま）
   - `is_completed === false` → ラベルに「未完了・進捗 X/8」を描画し「続きから再開」ボタン（`#tour-resume-btn`）を表示。クリックで `startOnboardingTourFrom(X - 1)`
   - `is_completed === true` → ラベルに「完了済み」を描画
6. 既存の自動起動・`endTour()` のサーバ完了送信（`onboarding-tour.js:186-195`）は変更しない。

### 4.3 テンプレート変更（`templates/settings/index.html`）

「オンボーディングツアー」行（58〜68 行付近）を拡張:

- 説明文の下に `<span id="tour-progress-label" class="…">` を追加（初期状態は空・非表示ではないがテキスト無し）。
- 既存「ツアーを開始」ボタンは維持（no-JS / status 取得失敗時のフォールバック）。
- 「続きから再開」ボタン `#tour-resume-btn` を `hidden` で追加。JS が状態に応じて表示切替。

```html
<span id="tour-progress-label" class="block text-xs font-semibold text-indigo-600 mt-1"></span>
…
<button id="tour-resume-btn" type="button" hidden onclick="window.startOnboardingTourFrom && window.startOnboardingTourFrom(Number(this.dataset.step||0))"
        class="…">続きから再開</button>
```

### 4.4 エッジケース

| ケース | 動作 |
|---|---|
| JS 無効 / fetch 失敗 | 現行表示のまま（「ツアーを開始」のみ）。壊れない |
| localStorage 利用不可（プライベートモード等） | 進捗表示は「未完了」のみ。続きから再開は非表示 |
| localStorage に古い形式の値 | 数値化できない場合は 0 扱い |
| ツアー対象要素が存在しないステップ | 既存のスキップ機構（`onboarding-tour.js:114-122`）に従う |
| ツアー完了 POST が失敗 | localStorage の完了フラグは残る（現行どおり）。status API は未完了を返すため再表示される=気づける |

## 5. G-3: ドキュメント整合

### 5.1 MANUAL.md（§3.5、177〜196 行付近）

1. **ツアー永続化の記述を修正**（現行 193 行）:
   - 誤: 「ツアーの進捗状況はユーザーごとにサーバへ永続化（`users.tour_progress`）され、…」
   - 正: 「ツアーの完了状態はユーザーごとにサーバへ永続化（`user_onboarding_states` テーブル・`UserOnboardingState`）され、端末を変えても再表示されません。設定画面には進捗（X/8）と「続きから再開」が表示されます。」
2. **文脈ヘルプの配備画面を修正**（現行 194〜196 行）:
   - 「登降園管理、連絡帳、指導案、請求設定などの主要画面右上に」→「**連絡帳一覧・出欠一覧・指導計画・請求設定・施設設定・設定診断の 6 画面**に」

### 5.2 README.md（72 行）

- 「主要画面折りたたみ文脈ヘルプ」→「主要 6 画面折りたたみ文脈ヘルプ、設定トップのツアー進捗表示」に更新（1 行修正のみ）。

### 5.3 確認事項

- MANUAL.md §3.5 の診断項目リストと `health_check_service.py` の 6 項目の対応は現状一致しているため変更不要。

## 6. 実装順序・コミット分割案

| 順 | コミット | 内容 | 目安 |
|---|---|---|---|
| 1 | `feat: deploy context help to attendance, billing, plans, facility settings` | G-1（4 テンプレート）＋テスト | 0.5人日 |
| 2 | `feat: show onboarding tour progress on settings page` | G-2（JS＋settings/index.html）＋テスト | 0.5人日 |
| 3 | `docs: align manual with tour persistence and context help deployment` | G-3（MANUAL.md・README.md） | 0.1人日 |

依存関係: G-1 と G-2 は独立（どちらが先でも可）。G-3 は G-1・G-2 の着地後。

## 7. テスト計画

### 7.1 新規テスト（G-1）

`tests/routers/test_context_help_deployment.py`（新設）:

- 既存パターン（`tests/services/test_health_check.py::test_health_check_http_endpoints` の TestClient + dependency_overrides）を流用。
- 各ページを適切な権限で GET し、`context-help-card` と `help_id` のマーカー文字列（例: `id="help-attendance-list"`）をアサート:
  - `/attendance`（職員）／`/billing/settings`（admin）／`/plans/`（職員）／`/settings/facility`（admin）
- 権限不足ロールで 403/リダイレクトになることの回帰確認（既存のアクセス制御を壊していないこと）。

### 7.2 新規テスト（G-2）

- テンプレートアサート: `/settings` レンダリングに `tour-progress-label`・`tour-resume-btn` が含まれること。
- API 回帰: 既存 `/settings/tour/status` のレスポンス契約（`tour_key`, `is_completed`, `completed_at`）が不変であること（既存テストがあれば実行、なければ 1 件追加）。
- JS はユニットテスト対象外（プロジェクト方針）。手動確認手順を §7.3 に記載。

### 7.3 手動確認（G-2）

1. 未完了ユーザーで `/settings` を開く → 「未完了・進捗 X/8」表示
2. ツアーを開始し 5 ステップ目まで進めて閉じる → 再読込で「進捗 5/8」＋「続きから再開」→ 5 ステップ目から再開されること
3. 別端末で完了 → 元端末で「完了済み」表示に切替
4. ホーム画面の初回自動起動が従来どおり動くこと

### 7.4 全体検証

- `python -m pytest tests/`（全件）
- `ruff check .`

## 8. リスクと代替案

| リスク | 影響 | 対策 |
|---|---|---|
| ヘルプ文言が画面の实际機能とずれる | 案内の信頼性低下 | §3.2 をドラフトと明記し、実装時に各画面操作で照合。未確定事項としてユーザー確認を取る |
| localStorage 進捗がサーバ完了状態と矛盾 | 「続きから再開」が完了済みでも出る | §4.1 のとおりサーバ `is_completed` を優先 |
| `plan_docs/home.html` 等のレイアウト崩れ | 見た目の劣化 | 既存 2 画面と同一コンポーネント・同一配置規則。ヘッダー直後固定。手動で 4 画面を目視確認 |
| settings/index.html の JS 追加で既存ボタンを壊す | ツアー再開不可 | 既存「ツアーを開始」ボタンと `restartOnboardingTour` は維持。JS 追加は表示の上書きのみ |

代替案: 進捗をサーバ保存する場合は `UserOnboardingState.progress: Optional[dict]`（JSON）を追加する必要がある（スキーマ変更・マイグレーション・バックアップ契約 `scripts/backup_contracts/schema-20261105.json` への同期が必要）。本ウェーブでは見送り、提案 ③ で検討する。

## 9. 未確定事項（実装前の合意ポイント）

1. **§3.2 のヘルプ文言**: 各画面の steps/cautions の文言は仮案。運用実態に合わせた修正の要否。
2. **G-1 の配置位置**: ページヘッダー直後でよいか（既存 2 画面と同一規則だが、出欠一覧は要素が多いので折りたたみ既定のまま＝閉じた状態で目立たない点の確認）。
3. **進捗表示の粒度**: 「X/8」の X は「最後に表示したステップ」ベース（本計画）。ステップ単位の明示的「既読」管理は行わない仕様でよいか。

## 10. 受け入れ条件（Definition of Done）

- [ ] 4 画面（出欠一覧・請求設定・指導計画・施設設定）に折りたたみ文脈ヘルプが表示され、開閉動作する（計 6 画面）
- [ ] 設定トップにツアー進捗（X/8 or 完了済み）が表示され、「続きから再開」で該当ステップから再開できる
- [ ] `/settings/tour/status`・`/tour/complete`・`/tour/reset` の API 契約が不変
- [ ] MANUAL.md・README.md の記載が実装と一致
- [ ] `python -m pytest tests/` 全件 GREEN・`ruff check .` GREEN
- [ ] DB スキーマ・マイグレーション・バックアップ契約に変更がないこと（`test_models_compat.py`・`test_backup_v2.py` が無変更で通ること）
