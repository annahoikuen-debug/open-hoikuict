# 実装計画書: コドモン参照の低コスト高効果改善 9 項目

- 日付: 2026-11-16
- 参照: https://www.codmon.com/ （業界シェアNo.1 保育ICT。連絡帳・出席・請求・通知・写真等をワンストップ提供）
- ステータス: **計画（未確定事項あり）。AGENTS.md の進め方に従い、各項目は「この計画書の該当節を変更書」としてモック試用 → 合意 → 実装の順で進める**
- 対象リポジトリ: open-hoikuict（FastAPI + Jinja2 + htmx + Tailwind / SQLModel + SQLite + Alembic / pytest + ruff）

## 1. 要望（9項目サマリ）

| # | 改善案 | 主な対象 | 難易度 | 期待効果 | スキーマ変更 |
|---|---|---|---|---|---|
| I1 | キーボードショートカット | `templates/base.html` / `static/js/` | 低 | 職員の日次操作速度向上 | なし |
| I2 | 定型文テンプレート | 連絡帳返信・お知らせ | 低〜中 | 記入負荷・記入漏れ削減 | **あり**（新テーブル） |
| I3 | 一括操作（連絡確認・打刻） | 出席・出席確認 | 低 | 朝の登園確認・一斉連絡の工数削減 | なし |
| I4 | 通知フィルタ拡充 | 保護者通知設定 | 低 | 通知過多防止・到達率向上 | **あり**（列追加3件） |
| I5 | 職員用横断検索 | 園児・お知らせ・連絡帳 | 低〜中 | 「どの画面だったか」探索時間削減 | なし |
| I6 | 帳票一括出力（ZIP/PDF） | `routers/document_exports.py` | 低〜中 | 月末事務の印刷工数削減 | なし |
| I7 | アクセシビリティ対応 | 共通テンプレート | 低 | 利用者層拡大・法令リスク低減 | なし |
| I8 | オフライン閲覧（保護者ポータル） | 既存 Service Worker 拡張 | 低 | 回線不安定時も情報閲覧可 | なし |
| I9 | 職員オンボーディングツアー | `base.html` + 新JS | 低 | 導入定着率・問い合わせ削減 | なし |

## 2. こちらの解釈（確定事項）

- 本計画は**提案と順序付け**であり、各項目の画面仕様はモック確認をもって確定とする（AGENTS.md 第1〜3条）。未確定の提案を確定仕様として扱わない。
- スキーマ変更を含むのは I2・I4 のみ。該当項目では Alembic マイグレーションと、**バックアップ契約JSONの再生成要否**を tasks で明示的に確認する（docs/implementation-plan-mfa-notice-fixes-2026-11-07.md の運用に倣う）。
- 通知の in_app 配信は現行どおり**常に作成**し、ミュート対象は push キューのみ（`notification_hub.py:309` の現行挙動を踏襲）。
- 既存実装との重複を避けるため、I4 は `ParentPushPreference`（models/core.py:2136）と `notification_hub._PREFERENCE_MUTE_COLUMNS`（notification_hub.py:91）を流用・拡張する。I6 は `document_exports.py` の `EXPORT_FORMAT_LABELS`（pdf/zip 定義済、document_exports.py:29）と `log_export` を流用する。I8 は保護者ポータルの `push_service_worker.js` と manifest（base.html:814）を拡張する。
- コミット・配備はユーザーの指示があってから実施する。

## 3. 実施順序（3ウェーブ）

```
Wave 1（スキーマ変更なし・即効果）: I1 → I9 → I7 → I3
Wave 2（小規模スキーマ/既存基盤拡張）: I4 → I5 → I8
Wave 3（新テーブル・帳票バッチ）: I2 → I6
```

各ウェーブ完了時に `python -m pytest -q`（全件）と `ruff check .` を実行し、GREEN を記録してから次へ進む。

---

## I1. キーボードショートカット

**目的**: 職員の頻出遷移（出席・連絡帳・ダッシュボード・検索）をキーボードだけで完結させる。

**画面仕様（要確認・モック対象）**
- `g` 2ストローク: `g d` ダッシュボード / `g a` 出席 / `g c` 連絡帳 / `g n` お知らせ
- `s`: ヘッダー検索ボックスへフォーカス（I5 と連動。I5 実装前は実装しない）
- `?`: ショートカット一覧モーダル
- テキスト入力・select・textarea・`contenteditable` フォーカス中は無効化
- 表示条件: base.html を継承する職員画面のみ。保護者・受付キオスクには適用しない

**実装ステップ**
1. `static/js/keyboard-shortcuts.js` を新規作成（依存ライブラリなし、約150行）。`data-shortcut-scope="staff"` 属性が base.html にある場合のみ起動。
2. `templates/base.html` に `<script src="/static/js/keyboard-shortcuts.js" defer></script>` を追加し、ナビ項目に `data-shortcut-target="attendance"` 等の属性を付与。
3. ヘルプモーダルを `templates/shared/shortcut_help.html` パーシャルとして追加。
4. テスト: JS のため自動テスト対象外。モック（`demo_screen_*.html` と同じ形式の架空データ HTML）で入力中無効化・遷移先を確認。

**工数目安**: 1人日 / **リスク**: htmx のキーイベントとの干渉 → 入力要素チェックで回避。

---

## I2. 定型文テンプレート（連絡帳返信・お知らせ）

**目的**: 返信・お知らせの定型文を登録・挿入でき、記入時間と揺れを減らす。

**データモデル（新規）** — `models/core.py` に追加:
```python
class StaffMessageTemplate(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scope: str            # "daily_contact_reply" | "notice"
    title: str            # 選択肢ラベル（例「体調返信（軽度）」）
    body: str
    sort_order: int = 0
    created_by: int | None = Field(default=None, foreign_key="user.id")
    created_at / updated_at: datetime
```

**実装ステップ**
1. モデル追加 + Alembic マイグレーション作成（`alembic revision --autogenerate`）。**バックアップ契約JSON再生成の要否を確認**。
2. `routers/message_templates.py` を新規作成。CRUD（GET /message-templates, POST, POST /{id}/update, POST /{id}/delete, すべて `verify_csrf`）。閲覧・編集権限は `staff_permissions.py` の既定ロールに合わせる（要確認: 管理者のみ編集か）。
3. 管理画面 `templates/message_templates/index.html` を作成し、`facility_settings` のナビから到達可能にする。
4. 連絡帳返信画面（`templates/daily_contacts/` 配下、`static/js/daily-contact-reply.js`）に「定型文から挿入」ボタン追加 → `<dialog>` で一覧 → 本文に追記挿入（既存入力を置換しない）。`GET /message-templates/options?scope=daily_contact_reply` を htmx/JSON で取得。
5. お知らせ作成画面にも同挿入 UI（scope=notice）。
6. テスト: `tests/routers/test_message_templates.py` 新規（CRUD・権限・CSRF）。返信エンドポイント（daily_contacts.py:283）の既存テストが壊れないことを確認。

**工数目安**: 2〜3人日 / **リスク**: 権限設計の未確定（モック時に確定）。

---

## I3. 一括操作（連絡確認依頼・出席打刻）

**目的**: 児童ごとの個別操作を複数児童へまとめて実行できるようにする。

**現状**: 出席確認依頼・確認応答は児童単位（routers/attendance_checks.py:457 `/{child_id}/contact-confirmation`, :511 `/{child_id}/verification`）。打刻も児童単位（routers/attendance.py:954 check-in, :996 check-out）。一括は未実装。

**画面仕様（要確認・モック対象）**
- 出席確認画面（roster）: 児童行にチェックボックス、ヘッダーに「全選択」「確認依頼を一括送信」ボタン。未送信児童のみ対象。二重送信はスキップ。
- 打刻一覧: 選択児童へ「一括入室 / 一括退室」。時刻はボタン押下時刻で全員同一（修正は既存の打刻訂正機能で対応）。
- 確認ダイアログで対象人数を表示してから実行。

**実装ステップ**
1. `POST /attendance-checks/bulk-contact-confirmation`（body: `child_ids: list[int]`, `verify_csrf`）。既存の児童単位処理（attendance_checks.py:457 の内部ロジック）をループで呼ぶ形にし、成功/スキップの件数を返す。
2. `POST /attendance/bulk-check-in` / `bulk-check-out`（同上）。既存 check-in/check-out（attendance.py:954, 996）のバリデーション（在園状態・当日有効性）を1児童でも失敗したら全体をロールバック（all-or-nothing）にするか部分成功にするかは**未確定事項**（既定: all-or-nothing）。
3. `templates/attendance_checks/` と `templates/attendance_list.html` にチェックボックス列と一括ボタンを追加。`static/js/attendance-roster.js` / `attendance-checks.js` に選択状態管理を追加。
4. テスト: `tests/routers/` に bulk エンドポイントのテスト（正常・1児童失敗時・権限なし・CSRF・二重送信スキップ）。

**工数目安**: 1.5〜2人日 / **リスク**: all-or-nothing の要否（モック時に確認）。

---

## I4. 通知フィルタ拡充（保護者側の種別ミュート）

**目的**: `notice_published` / `survey_published` / `fever_notification` も保護者が push オフにできるようにする（現行は `_PREFERENCE_MUTE_COLUMNS` が None で常に配信、notification_hub.py:96-98）。

**データモデル**: `ParentPushPreference`（models/core.py:2136）へ列追加（すべて `default=True`）:
- `notice_published_enabled: bool`
- `survey_published_enabled: bool`
- `fever_notification_enabled: bool`

**実装ステップ**
1. モデルへ列追加 + Alembic マイグレーション。**バックアップ契約JSON再生成の要否を確認**。
2. `notification_hub._PREFERENCE_MUTE_COLUMNS` の該当3種別を列名に更新。
3. `templates/parent_portal/push_settings.html` に3トグルを追加（既存の attendance/closure トグルと同一UI）。保存処理は既存の設定保存ルート（routers/parent_push.py 配下）を拡張。
4. 緊急（`emergency_notice`）は force_push の現行どおり**ミュート不可**であることを画面文言に明記。
5. テスト: `tests/test_notification_hub.py` に「種別ごとにミュートされた保護者へ push キューが作られない／in_app は作られる」ケースを3種分追加（既存 `test_muted_parent_receives_in_app_only`:231 を雛形に）。

**工数目安**: 1〜1.5人日 / **リスク**: 既存端末の preference 行がない保護者（新規列は default=True なので影響なし）。

---

## I5. 職員用横断検索

**目的**: ヘッダーの1入力欄から園児・保護者・お知らせ・連絡帳を横断検索する。

**画面仕様（要確認・モック対象）**
- base.html ヘッダー右に検索ボックス。`/staff/search?q=` へ GET。
- 結果画面は種別ごとのグループ表示（園児 / 保護者 / お知らせ / 連絡帳）× 各上位10件、「もっと見る」は対象セクションへの絞り込みリンク。
- v1 は LIKE 検索（SQLite）。権限は各モジュールの既存表示条件を踏襲（職員権限で見えないデータは検索結果にも出さない）。

**実装ステップ**
1. `routers/search.py` 新規。`GET /staff/search`。検索対象: `Child`（氏名・ふりがな）、`ParentAccount`/家族名、`Notice`（表題・本文）、`daily_contact`（本文）。各クエリで既存の権限スコープ関数を適用。
2. `templates/shared/search_results.html` 新規 + `routers/main.py` へ include。
3. base.html に検索フォーム追加（I1 の `s` ショートカットと連動）。
4. テスト: `tests/routers/test_search.py` 新規（各種別ヒット・権限で除外されること・XSS エスケープ）。
5. 将来拡張（本計画の対象外）: SQLite FTS5 化、請求・シフトへの対象拡大。

**工数目安**: 2人日 / **リスク**: 権限漏れ（情報が出過ぎる）→ 各モジュール既存の権限ヘルパーを必ず経由。

---

## I6. 帳票一括出力（ZIP/PDF バッチ）

**目的**: 「月次 × 複数クラス」など複数帳票を1操作で ZIP 取得できるようにする。

**現状**: `document_exports.py` にエクスポート基盤あり（dashboard:45 / history:82 / preview:130 / log_export:213、`EXPORT_FORMAT_LABELS` に pdf・zip 定義済）。月次印刷エクスポートの個別実装は docs/implementation-monthly-print-export-2026-09-27.md。

**実装ステップ**
1. `EXPORT_TYPES` にバッチ型を追加: `monthly_class_batch`（対象月 + クラス複数選択 → 1クラス1PDF を ZIP 化）。生成処理は既存の単体 PDF 生成関数をループ呼びし、`zipfile` でアーカイブ（生成は同期・小規模前提。大きくなる場合は background_jobs 化を検討→未確定事項）。
2. `log_export` にバッチ型・件数を記録（history 画面に反映）。
3. `templates/document_exports/` ダッシュボードにクラス複数選択 UI（チェックボックス）を追加。
4. テスト: `tests/routers/` に ZIP 生成テスト（エントリ数・ファイル名規則・空クラス選択時の 400）。

**工数目安**: 2人日 / **リスク**: 既存の月次印刷実装と仕様が二重化しないよう、生成ロジックは既存関数を再利用（新規テンプレートを作らない）。

---

## I7. アクセシビリティ対応（段階的）

**目的**: 共通テンプレート起点で最小コストの a11y ベースラインを作る。

**実装ステップ（ベースライン）**
1. `templates/base.html`: 本文への skip link（既存 print CSS と同じく共通化）、`:focus-visible` の可視スタイル、`lang="ja"` は既存（base.html:2）確認済。
2. 主要10画面のフォームで `label` と入力部品の `for`/`id` 紐付け棚卸し（チェックリスト: templates/attendance/, daily_contacts/, notices/, parent_portal/）。
3. Tailwind カラークラスのコントラスト棚卸し（`text-slate-400` 等の薄色の本文利用を `text-slate-600` 以上へ）。対象は「本文・ボタン文言」のみで、装飾は対象外。
4. アイコンのみのボタンに `aria-label` 追加。
5. テスト: 自動化はしない。docs に `docs/accessibility-checklist.md` を作り、モック確認時のチェック項目として運用。Lighthouse a11y スコアをベースライン記録。

**工数目安**: 1〜2人日（ベースラインのみ。全画面網羅はフォローアップ）

---

## I8. オフライン閲覧（保護者ポータル限定）

**目的**: 回線が不安定な環境でも、以前閲覧したお知らせ一覧・詳細が読めるようにする。

**現状**: 保護者ポータルには push 用 SW（templates/parent_portal/push_service_worker.js）と manifest（base.html:814）があるが、ページのオフラインキャッシュは未実装。受付端末（guardian_service_worker.js:118）はシェルキャッシュ実装済み。

**画面仕様（要確認・モック対象）**
- 対象: `/parent-portal/notices` 一覧と詳細のみ（v1）。書き込み系（返信・請求）は対象外。
- 戦略: network-first（3秒タイムアウトで cache fallback）。キャッシュ表示時は画面上部に「オフラインで閲覧中の情報です（取得日時: …）」バッジを表示。
- キャッシュは SW 内で当日日付のエントリのみ保持（深夜に古い情報を出さない）。

**実装ステップ**
1. `push_service_worker.js` に cache-first の fetch ハンドラ追加（既存の push ハンドラは維持）。`?v=` クエリでバージョン更新（現行の `?v=20260830-2` 方式に倣う、push_settings.html:133）。
2. 詳細ページにオフラインバッジ用の小スクリプト追加。
3. テスト: 自動テスト対象外。実機確認手順を `docs/parent-push-real-device-test.md` に追記（オフライン時の表示・復帰時の再取得）。

**工数目安**: 1人日 / **リスク**: 古い情報の誤認 → バッジ必須化と日付バウンダリで緩和。

---

## I9. 職員オンボーディングツアー

**目的**: 初回ログイン職員が主要画面の所在をつかめるようにする。

**画面仕様（要確認・モック対象）**
- 職員ホーム（routers/staff_portal.py:510 `/staff/portal`）初回表示時に、5ステップのスポットライトツアー（ホーム / 出席 / 連絡帳 / お知らせ / 設定）。
- 「完了」「後で」を保存。再表示は設定画面の「もう一度ツアーを見る」から。
- 完了状態は **localStorage**（v1）。サーバ保存（ユーザー単位）は未確定事項（複端末職員にはサーバ保存が良い）。

**実装ステップ**
1. `static/js/onboarding-tour.js` 新規（依存なし・約200行。`data-tour-step` 属性をナビから参照、スポットライトは `box-shadow` ベース）。
2. `templates/base.html` のナビ要素に `data-tour-step` 属性付与、ヘルプモーダル（I1）と共通化。
3. 設定画面に「もう一度ツアーを見る」ボタン（localStorage キーを消してリロード）。
4. テスト: 手動確認。JS のため自動テスト対象外。

**工数目安**: 1.5人日 / **リスク**: レイアウト変更で step 対象が消える → `data-tour-step` が無いステップはスキップする防御コード。

---

## 4. 共通検証プロセス

1. **モック**: UI を伴う I1〜I9 全項目は、`demo_screen_*.html` と同形式の架空データ HTML を作り、未入力/入力済み/エラー状態を切替可能にして確認してもらう（本番 DB・送信処理に接続しない）。
2. **実装後**: 合意モックと画面を照合し、各項目のテスト追加を実行。
3. **ウェーブ完了時**: `python -m pytest -q` 全件 + `ruff check .` を実行し結果を記録。
4. **配備**: ユーザーの依頼に従い、最新の更新記録を確認してから実施（AGENTS.md 配備条項）。

## 5. 未確定事項（モック確認時に確定）

1. **I2**: 定型文の編集権限（管理者のみ / 全職員）。既定は「管理者のみ編集・全職員利用」。
2. **I3**: 一括打刻の失敗時方針（all-or-nothing / 部分成功）。既定は all-or-nothing。
3. **I4**: in_app 通知も種別で非表示にするか（現行踏襲の push のみにするか）。既定は push のみ。
4. **I5**: 検索対象への請求・シフト追加要否（v1 対象外で進める）。
5. **I6**: バッチ生成の同期実行上限（クラス数しきい値、超過時の background_jobs 化要否）。
6. **I9**: ツアー完了状態のサーバ保存要否。
7. **I2/I4**: スキーマ変更に伴うバックアップ契約JSONの再生成要否（実装タスク冒頭で確認）。

## 6. 想定総工数

| ウェーブ | 項目 | 合計 |
|---|---|---|
| Wave 1 | I1(1) + I9(1.5) + I7(1.5) + I3(2) | 約6人日 |
| Wave 2 | I4(1.5) + I5(2) + I8(1) | 約4.5人日 |
| Wave 3 | I2(3) + I6(2) | 約5人日 |
| **合計** | | **約15.5人日** |
