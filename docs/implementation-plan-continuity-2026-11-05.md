# 計画類の転記削減 実装計画書（案2・案3・案4）— 2026-11-05

ステータス: **計画（モック確認前）**。本書は[AGENTS.md](../AGENTS.md)の手順（仕様確認 → モック試用 → 実装 → 照合・テスト）に従い、確定事項と未確定事項を分けて記述する。未確定の提案を確定仕様として扱わないこと。

- 提案元: 2026-11-05 の機能評価における9改善案のうち **案2（月案 前月引き継ぎ）・案3（週案→日案展開）・案4（振り返りパイプライン）**
- 対象読者: 本リポジトリの実装者・レビュアー
- 関連仕様: [spec-weekly-daily-plans.md](spec-weekly-daily-plans.md) / [spec-daily-plan-v1.md](spec-daily-plan-v1.md) / [monthly-library-proposal-2026-09-27.md](monthly-library-proposal-2026-09-27.md)

---

## 1. 背景と目的

計画類（年案・月案・週案・日案）と日々の記録（振り返り）は独立した文書として成立しているが、**上位計画→下位計画、前月→当月、前日→翌日の受け渡しは職員の手動転記に依存している**。

| 現行の転記箇所 | 現状のコード | 職員の負担 |
| --- | --- | --- |
| 前月月案 → 当月月案 | `monthly_library` は空シートから開始（`plan_docs/services/monthly_library.py:83` `new_sheet`）。前月は履歴APIで見るだけ（`plan_docs/routers/monthly_library.py:209`） | 全セル再入力または履歴を見ながら写経 |
| 週案の主な活動 → 日案の1日の流れ | 週案グリッドは `attach_weekly_grid` で月〜金の行を作るだけ（`plan_docs/services/generators.py:177`）。日案フォームは手入力（`templates/plan_docs/daily_plans/form.html`） | 週5日×主活動の再入力 |
| 日案の振り返り → 翌日・翌週・翌月 | 振り返りは `plan_docs/services/daily_reflections.py` で保存されて終わり。次の計画フォームへ自動反映されない | 「子どもの姿」を思い出して書き直す |

目的: **同じ内容を2回書かせる導線を、参照・引用・自動充填に置き換える**。既存の契約（`PlanDocument` / `section_key` / `source_refs` / 楽観ロック / 月案帳票JSON）を壊さず、追加のみで実現する。

## 2. スコープ

### 対象（本計画で実装）

| 案 | 機能 | 主体 |
| --- | --- | --- |
| 案2 | 月案帳票の「前月から引き継ぎ」（同クラス・同年齢の保存済み月案を複製し差分編集） | `plan_docs`（monthly-library） |
| 案3 | 週案グリッド → 日案タイムラインの事前入力と「週から日案一括作成」 | `plan_docs`（plans / documents） |
| 案4 | 提出済み振り返りの次計画への事前入力（週案・月案フォーム）と日案フォームの参照パネル | `plan_docs`（plans / documents） |

### 対象外

- DBスキーマ変更（Alembicマイグレーション不要の方針。月案は `monthly_sheet` JSON、計画は既存カラムのみで実現する）
- 連絡帳（案5）、園方針マスタ（案8）、AI候補の文脈拡張（案6）は別計画
- 共通文例DB（`bunrei.sqlite`）の内容追加・再生成
- 承認フロー（draft → in_review → approved）の変更

## 3. 要望・解釈・未確定事項の分離

### 3.1 要望（ユーザー発話の要約）

1. スタッフが計画類（年案・月案・週案・日案）を「楽勝」で作成できるようにしたい。
2. 文書・連絡帳を簡単に作れるようにしたい（本計画では計画類に限定）。
3. 何回も転記することを減らしたい。

### 3.2 こちらの解釈

- 「転記の削減」は入力欄の削減ではなく、**既に入力済み・提出済みの内容を正しい出所付きで初期値にすること**を指す。
- 引用した値は編集可能なまま残し、出所（どの文書・どの欄由来か）を画面で追跡できること。これは既存の `source_refs` / `origins` の文化と一致する。
- 一括処理（案2の複製、案3の一括作成）は **下書き（draft）の作成に限定** し、承認フローを自動で進めない。

### 3.3 未確定事項（モック確認で決める）

| # | 未確定事項 | 仮置り（推奨） |
| --- | --- | --- |
| Q1 | 案2: 引き継ぎは即時下書き保存か、フォーム事前入力のみか | **即時下作成（POSTでdraft作成）**。誤作成は管理者アーカイブで対応 |
| Q2 | 案2: 年齢跨ぎ（例: 3月2歳児 → 4月3歳児）の引き継ぎ | **共通3欄（`common:goal` `common:home` `common:review`）のみコピー＋通知**。それ以外は空 |
| Q3 | 案2: 出典（`origins`）を複製に含めるか | **含める**（引き継いだ本文の出所として履歴が正になる） |
| Q4 | 案3: 一括作成の土曜扱い | **週案の `include_saturday`（グリッドに土行があるか）に従う** |
| Q5 | 案3: 日案フォームへの週案事前入力の適用範囲 | **第1行の `activity_name`（主な活動）＋週案ねらいの参照表示**。時間・援助・配慮は空 |
| Q6 | 案4: 週案の「前週の振り返り」の引用元 | **前週週案の `weekly_reflection_viewpoint` 本文を主値に、前週の日案提出済み振り返りは参照パネル** |
| Q7 | 案4: 参照パネルに載せる振り返りの状態 | **`submitted` のみ**（draftは未確定のため載せない） |
| Q8 | 案4: 日案フォームの引用先 | **第1行「子どもの様子」へワンクリック挿入（クライアント側のみ）**。データ契約は変えない |

---

## 4. 機能仕様

> 以下は仮置りの推奨値（§3.3）を前提にした設計。Q1〜Q8の回答により、該当節を修正してからモック→実装へ進む。

### 4.1 案2: 月案 前月引き継ぎ

#### 4.1.1 データ

- 引き継ぎ元の特定: `monthly_sheet_key = json.dumps([nursery_ref, classroom_id, previous_month, age])`（`plan_docs/store.py:172` と同じ生成規則）で `PlanDocumentRow` を1件検索。`deleted_at` が設定された文書（head経由）は除外。
- `previous_month`: `target_month` の直前暦月（`plan_docs/services/monthly_library.py:77` `previous_months` の n=1 と同じ暦計算）。年度替わり（2026-04 ← 2026-03）も暦月で処理する。
- 複製内容:
  - 同一 `template_id`（同一年齢）の場合: 元シートの `fields` 全欄の `body` と `origins` をコピーし、各欄に `"carried_from": "<前月YYYY-MM>"` を付与する。
  - 年齢跨ぎ（Q2 採用時）: 両テンプレートに存在する共通欄のみコピー。判定は `field_definitions()`（`plan_docs/services/monthly_library.py:99`）の積集合で行う。
- 名簿: 複製後に既存の `_scope` 名簿追加ロジック（`plan_docs/routers/monthly_library.py:56-61`、age<3のみ）をそのまま通す。**退園児の欄は削除しない**（現行契約「既存園児の本文を動かさない」を維持）。
- `validated_fields`（`plan_docs/services/monthly_library.py:203`）と `SaveInput.CellInput` に `carried_from: str | None` を追加し、保存後も枯れないようにする（`extra="forbid"` は新フィールド追加と両立）。

#### 4.1.2 API

| 項目 | 仕様 |
| --- | --- |
| エンドポイント | `POST /plans/monthly-library/carry-over`（JSON） |
| 入力 | `classroom_id`, `target_month`, `age`（`_scope` で検証） |
| 成功 | 対象月の文書が**存在しない**場合のみ、引き継ぎ済みシートで draft を作成し `_context` を返す（200）。`lock_version=1`、リビジョン1件（reason=`created`、`snapshot` に引き継ぎ元月を含む `carried_from` を記録） |
| 404 | 引き継ぎ元の保存済み月案が無い／参照権が無い |
| 409 | 対象月の文書が既に存在する／`template_version` 不一致（既存の409文言に合わせる） |
| 権限 | `require_can_edit` + CSRF（既存の `POST /save` と同一条件） |

#### 4.1.3 画面（`templates/plan_docs/monthly_library/_sheet.html` + `static/js/monthly-library.js`）

- 表示条件: 対象（クラス・月・年齢）の文書が未保存、かつ引き継ぎ元が存在するとき `#carry-over` ボタンを表示（`_context` に `carry_over: {"available": bool, "from_month": "2026-09", "cross_template": bool}` を追加）。
- 遷移: ボタン → 確認ダイアログ（コピー範囲・出所付きである旨・前月側は変更されない旨）→ POST → `context` 再取得。
- 保存タイミング: POST時に下書き保存（Q1）。以後は通常の `#save`。
- 修正: 引き継ぎ後も全セル通常編集。`carried_from` バッジは「前月から」表示として残す（出典扱い）。
- 取消: v1は削除不可。誤って作成した場合は管理者によるアーカイブ（現行の `update_status(archived)`）で対応。

#### 4.1.4 出力への影響

- `monthly_export_layout.make_layout` は `body` のみを消費するため、`carried_from` は出力に影響しない（`plan_docs/services/monthly_export.py:144`）。PDF/Excelの出力結果は引き継ぎ有無で変わらない。

### 4.2 案3: 週案グリッド → 日案展開

#### 4.2.1 週案の参照方法

- 対象日のISO週月曜（`date.fromisocalendar`）を算出し、`PlanDocumentRow` を `document_type=weekly_plan` + `classroom_ref` 一致 + `week_start_date` 一致 + `nursery_ref` 一致で検索。複数ある場合は `updated_at` 降順の先頭（`store.list` と同じ順序）。`archived` は除外。
- 見つかった週案の `schedule.layout == "weekly_grid"` の曜日行（`row_key` = mon/tue/wed/thu/fri/sat）から対象曜日の `cells["activity"].body` と `cells["support"].body` を取り出す。

#### 4.2.2 日案フォームの事前入力（Q5）

- `GET /plans/daily-plans/new?target_date=...&classroom_ref=...` で週案が見つかった場合:
  - `timeline_rows[0].activity_name` に週案の該当曜日 `activity` 本文を初期値として表示（`form_values` 経由。ユーザー入力がある再描画では常に `form_values` 優先で上書きしない）。
  - フォーム上部に参照パネル「この週の週案: 〈タイトル〉（状态）」+ 週案へのリンクを表示。
  - `POST /plans/daily-plans` に `parent_document_id`（hidden、任意）を追加し、`generate_simple_daily_plan` が受け取ったIDをそのまま `PlanDocument.parent_document_id` に設定する。IDはサーバー側で「週案・同クラス・同園」であることを再検証する（`_resolve_parent_document_id` と同じ規約、`plan_docs/routers/plans.py:78`）。
  - セルの `source_refs` に `weekly.document:{id}` を追加（`evidence_tags_for` は `weekly.` → 「入力」タグで既存動作）。
- 週案が無い・別クラス・アーカイブ済みの場合は現行どおり空フォーム（エラーにしない）。

#### 4.2.3 週から日案一括作成

| 項目 | 仕様 |
| --- | --- |
| エンドポイント | `POST /plans/daily-plans/bulk-from-weekly`（フォーム: `target_week`, `classroom_ref`） |
| 対象日 | 週案グリッドに行が存在する曜日のみ（Q4: `include_saturday` で土も）。各日の `timeline_rows` = `[{"activity_name": 週案セル, "time_label": "", ...}]` |
| 保存 | 各日を独立した `repository.create` で draft 保存。`parent_document_id` と `age_class` は週案から継承 |
| スキップ | 既に同 `nursery_ref+classroom_ref+target_date` の日案（head の一意制約、`plan_docs/db_models.py:127`）が存在する日は作成しない。`IntegrityError` は日単位で `rollback` して継続 |
| 応答 | カレンダーへ303リダイレクト。クエリで `created=N&skipped=M&failed=K` を通知表示 |
| エラー | 週案なし404 / 編集権なし403 / クラスアクセス不可403（既存文言に整合） |

#### 4.2.4 画面

- 週案詳細（`templates/plan_docs/documents/detail.html`）: 週案かつ `can_edit` のとき「この週の日案を一括作成」ボタン＋未作成日数の表示。
- 日案カレンダー（`templates/plan_docs/daily_plans/calendar.html`）: その週・そのクラスに週案が存在する未作成セルに「週案から作成」バッジ（通常の新規フォームへのリンクに事前入力パラメータを付す）。カレンダー1レンダリング内の週案ルックアップはN+1にならないよう週単位で一括取得する。

### 4.3 案4: 振り返りパイプライン

#### 4.3.1 引用元の定義

| 次の計画 | 引用元（Q6/Q7採用時） | 取得方法 |
| --- | --- | --- |
| 週案フォーム `previous_week_reflection` | 前週の週案（同クラス・最新非アーカイブ）の `weekly_reflection_viewpoint` 本文 | `repository.list(weekly_plan)` → `week_start_date` フィルタ |
| 月案フォーム `previous_reflection` | 前月の月案（同クラス・最新非アーカイブ）の `monthly_reflection_viewpoint` 本文 | `repository.list(monthly_plan)` → `target_month` フィルタ |
| 週案・月案フォームの参照パネル | 前週/前月の**提出済み**日案振り返り（`PlanDailyReflectionRow.status == "submitted"`、同クラス、日付降順・上限10件） | `reflections_by_document_id`（`plan_docs/services/daily_reflections.py:57`）+ 日案結合 |
| 日案フォームの参照パネル | 前営業日の同クラス日案の提出済み振り返り。前営業日は土日を除外（月曜なら前週金曜） | `target_date` 逆順で最初の `submitted` |

#### 4.3.2 画面と保存

- 週案フォーム（`templates/plan_docs/weekly_plans/form.html`）: `target_week` がクエリで指定された場合のみサーバー側で事前入力（v1）。フォーム上で週を変更した場合の動的再取得は拡張としてモック確認後に判断する。`form_values` に既存入力がある場合は上書きしない。
- 月案フォーム（`templates/plan_docs/monthly_plans/form.html`）: GET時に前月値が決まるため、サーバー側で無条件に事前入力（既存入力が無い場合のみ）。
- 日案フォーム（`templates/plan_docs/daily_plans/form.html`）: 前営業日の提出済み振り返りがあるとき、折りたたみ参照パネルを表示し「第1行の子どもの様子へ挿入」ボタンを置く（Q8、クライアント側のみ・送信データ契約は不変）。
- 保存タイミング: すべて**作成POST時の従来保存のみ**。事前入力・パネルは永続化しない。
- 取消: 入力クリアのみ。引用元文書の状態に影響しない。
- 出所表示: パネルには引用元文書タイトル・対象期間・状態ラベルを出す。v1では本文に `source_refs` を追加しない（データ契約を変えない。要望があれば拡張）。

#### 4.3.3 副作用の禁止事項

- 振り返りの draft/submit の遷移、`16:30` 締切リマインダ、提出後編集時の再提出要件（`plan_docs/services/daily_reflections.py`、既存テスト `test_daily_reflection_submission_calendar_status_and_reminders`）は**一切変更しない**。
- 提出済み振り返りの編集（draft化）は、既に引用済みの次計画の本文に影響しない（事前入力は作成時点の値で固定される）。

---

## 5. 実装ステップとファイル

| Phase | 内容 | 主な変更ファイル | 目安 |
| --- | --- | --- | --- |
| 0 | 仕様確認・モック（§3.3 のQ1〜Q8を確定） | リポジトリ直下 `demo_screen_plan_carryover.html` / `demo_screen_weekly_daily_expand.html` / `demo_screen_reflection_pipeline.html`（架空データのみ・本番DB/送信処理に非接続。未入力/入力済み/一部入力/エラーを切替できること） | 0.5日 |
| 1 | 共通サービス（暦・週・前営業日・共通欄判定・引き継ぎ元検索の純関数） | 新規 `plan_docs/services/continuity.py` | 0.5日 |
| 2 | 案2 実装 | `plan_docs/routers/monthly_library.py`（carry-overエンドポイント、`_context` 拡張）、`plan_docs/services/monthly_library.py`（`SaveInput.CellInput.carried_from`、`validated_fields` 通過）、`static/js/monthly-library.js`、`templates/plan_docs/monthly_library/_sheet.html` | 1.5日 |
| 3 | 案3 実装 | `plan_docs/routers/plans.py`（`new_daily_plan` 事前入力、`create_daily_plan` の `parent_document_id`、bulkエンドポイント）、`plan_docs/services/generators.py`（`generate_simple_daily_plan` に parent/source_ref 受渡し）、`templates/plan_docs/daily_plans/form.html`、`templates/plan_docs/daily_plans/calendar.html`、`templates/plan_docs/documents/detail.html` | 2日 |
| 4 | 案4 実装 | `plan_docs/routers/plans.py`（週案・月案フォームの事前入力）、`plan_docs/services/continuity.py`（振り返り参照取得）、`templates/plan_docs/weekly_plans/form.html`、`templates/plan_docs/monthly_plans/form.html`、`templates/plan_docs/daily_plans/form.html` | 1.5日 |
| 5 | 検証・文書 | §6のテスト全実行、`ruff check .`、`docs/features.md` と `MANUAL.md` の該当節追記 | 0.5日 |

配備時の注意（AGENTS.mdより）: 配備作業では最新の更新記録を確認する。開発ブランチと本番用ブランチの機能が異なる場合があるため、既存の本番機能を失う更新をしない。本計画は追加のみで、既存エンドポイントの契約を変えない。

## 6. テスト計画（リグレッション防止）

### 6.1 方針

- 既存のテスト規約に従う: `unittest.TestCase` + インメモリSQLite（`StaticPool`）+ `SQLModel.metadata.create_all` + `TestClient`、CSRFは `test_monthly_library.py:60-86` と同じ手順。**本番DB・稼働中DB・コーパスを絶対に開かない**（`test_monthly_library.py:89` の読み取り専用検証を踏襲）。
- DBスキーマを変更しないため、`tests/snapshots/models_public_names.txt` と Alembic 関連テストは無変更で通ることを一回確認する。

### 6.2 新規テスト

#### `tests/routers/test_monthly_carryover.py`（案2）

| テスト | 検証内容 |
| --- | --- |
| 同一年齢で全欄複製 | body/origins/carried_from が写る。元文書の `monthly_sheet` が**不変**。コーパスファイルが不変 |
| 対象月が既存 → 409 | 既存文書の fields/lock_version が変わらない |
| 引き継ぎ元なし → 404 | 空シートの通常作成は従来どおり可能 |
| 年齢跨ぎ（2歳→3歳） | 共通3欄のみ、`cross_template=true` 通知（Q2） |
| 名簿差分 | 追加園児は空欄で追加、退園園児の欄は保持（既存 `_scope` 契約の再確認） |
| 年跨ぎ（2027-01 ← 2026-12） | `previous_month` 計算 |
| 権限・CSRF | view_only 403 / CSRF無し403 / 他クラス403 / 他園404（`test_auth_permissions_and_csrf` と同型） |
| リビジョン | 作成後 `lock_version=1`・リビジョン1件・snapshot に `carried_from` 記録 |
| 保存の往復 | `carried_from` が `validated_fields` を通っても枯れない。既存 origins が壊れない（`test_no_source_still_allows_manual_save_and_preserves_existing_sources` の再確認） |

#### `tests/routers/test_weekly_daily_expansion.py`（案3）

| テスト | 検証内容 |
| --- | --- |
| 日案フォーム事前入力 | 週案の該当曜日 activity が第1行に表示、週案参照パネル表示。`form_values` 入力済みなら上書きしない |
| 週案なし/他クラス/アーカイブ | 事前入力なしで現行どおり（エラーにしない） |
| parent_document_id 検証 | 作成時に正当な週案IDのみ受入れ、偽造IDは現行の `_resolve_parent_document_id` 規約どおり無効化。serializer 出力に現れる |
| 一括作成の正常系 | 月〜金5件draft作成・各日 `parent_document_id`・`age_class` 継承・`source_refs` に `weekly.document:{id}` |
| 一括の部分再実行 | 既存日はスキップされ `created/skipped` が正しい。土行なし週案で土を作らない（Q4） |
| 一括の異常系 | 週案なし404 / view_only 403 / 他クラス403 / 一部失敗時も他日は保存され `failed=K` が返る |
| カレンダー表示 | 週案保有週の未作成セルにバッジ、N+1ルックアップが発生しない（クエリ数の上限アサート） |

#### `tests/routers/test_reflection_pipeline.py`（案4）

| テスト | 検証内容 |
| --- | --- |
| 週案事前入力 | 前週週案の `weekly_reflection_viewpoint` が初期値。他クラス/アーカイブ/不在では空 |
| 月案事前入力 | 前月月案の `monthly_reflection_viewpoint`。年跨ぎ（2026-04 ← 2026-03） |
| 参照パネル（週・月） | `submitted` のみ（Q7）。draft は出ない。他クラスの振り返りは出ない。上限件数 |
| 日案参照パネル | 前営業日が土日の場合は前週金曜の提出済み振り返り。`target_date` 未指定時は出ない |
| 既存遷移の非破壊 | 振り返りの draft/submit/再提出・リマインダが従来どおり（既存テストの内容を土台に本機能経由でも再確認） |
| 引用後の編集 | 事前入力値を消しても保存可能。引用元文書は不変 |

#### `tests/services/test_plan_continuity.py`（純関数）

- `previous_month("2026-03") == "2026-02"`、`previous_month("2026-01") == "2025-12"`、不正入力の拒否
- ISO週月曜算出・`week_start_date` 突合・前営業日（金→月、月→金）
- 年齢跨ぎの共通欄積集合（`common:goal/home/review` のみ）

### 6.3 既存テスト（退行ガードとして必ず通す）

```bash
# 機能単位
python -m pytest tests/routers/test_monthly_library.py tests/routers/test_monthly_export.py tests/routers/test_monthly_ai.py tests/routers/test_monthly_restore.py tests/routers/test_monthly_weekday.py -x -q
python -m pytest tests/routers/test_plan_docs.py -x -q

# 全量・静的検査
python -m pytest tests/ -q
ruff check .
```

| 既存テスト | 守られる契約（本計画が壊してはならないもの） |
| --- | --- |
| `test_monthly_library.py::test_save_roundtrip_sources_revision_and_conflict` | 保存往復・409競合・リビジョンsnapshot |
| `test_monthly_library.py::test_roster_additions_keep_existing_children_and_empty_month_is_missing` | 名簿追加で既存園児の本文を壊さない |
| `test_monthly_library.py::test_reject_forged_fields_sources_and_foreign_document` | `validated_fields` の欄検証（`carried_from` 追加で緩めない） |
| `test_monthly_library.py::test_reviewed_document_is_readonly_and_unauthenticated_detail_hidden` | 承認後は編集不可・未認証の404 |
| `test_monthly_export.py` | 月案出力レイアウト（bodyのみ消費・`carried_from` 無影響） |
| `test_monthly_ai.py` | AI候補の署名・スコープ（案2〜4で触らない） |
| `test_plan_docs.py::test_daily_plan_is_persisted_with_head_and_immutable_revision` | 日案の sections 構成・head/revision 不変性（事前入力で壊さない） |
| `test_plan_docs.py::test_daily_reflection_submission_calendar_status_and_reminders` | 振り返りの状態遷移・締切リマインダ |
| `test_plan_docs.py::test_edit_uses_optimistic_lock_and_creates_revision` | 楽観ロック（一括作成・事前入力はこの経路を変えない） |
| `test_plan_docs.py::test_daily_plan_calendar_shows_activity_and_missing_class_days` | カレンダーのURL・aria-label 形式（バッジ追加で既存表記を壊さない） |

### 6.4 受入基準

1. §6.2の全テストが新規追加され、§6.3を含む `python -m pytest tests/ -q` が全件パス、`ruff check .` がゼロ件。
2. モックで合意した表示条件・遷移・保存タイミング・取消動作（§4.1.3 / §4.2.4 / §4.3.2）と実装の動作が一致する。
3. 引き継ぎ・一括作成・事前入力のいずれも、**元の文書・コーパス・他クラスのデータを変更しない**。
4. `docs/features.md` と `MANUAL.md` に新操作が記載されている。

## 7. リスクと対処

| リスク | 対処 |
| --- | --- |
| 一括作成の部分失敗で二重作成・整合崩れ | 日単位の `try/except` + `rollback`、head一意制約を頼りに冪等な再実行を保証。`failed=K` を明示表示 |
| 事前入力がユーザー入力を上書き | 事前入力はGET初期描画のみ。再描画は常に `form_values` 優先（テストで担保） |
| 引き継ぎで前月の出典が不当に正当化される | `needs_review` を維持し「確認してから使ってください」表示を引き継ぐ。`carried_from` で前月由来を明示 |
| 退園児データが当月帳票に残る | 現行契約（削除しない）を維持。出力に含まれる点は `_sheet.html` の既存注記に追記して周知 |
| カレンダーの性能劣化 | 週案ルックアップは表示月×クラス単位で一括取得しN+1を回避（テストでクエリ数をアサート） |
| ロールバック | 新規エンドポイントとUI追加のみでスキーマ変更なし。機能単位でボタン/ルートを外せば無効化できる |

## 8. 決めていただくこと（モック確認時）

1. Q1〜Q8（§3.3）の回答。
2. 一括作成ボタンの配置（週案詳細のみか、日案カレンダーにも置くか）。
3. `carried_from` バッジの見せ方（常時表示か、`details` 折りたたみか）。

回答後、Phase 0のモックを現行配備版の画面構成（既存入力項目を省略しない）に合わせて作成し、試用してから実装に入る。
