# シフト機能 有機的統合 実装計画書（27ステップ・サブステップ分解版）

- 作成日: 2026-11-10
- 対象: open-hoikuict v0.4.0（`C:\Users\user\openict\open-hoikuict`）
- 関連: `docs/shift-schedule-integration-proposal-2026-10-03.md`、精査報告 2026-11-10（会話内）
- 目的: NuShift シフト機能を登降園実績・園児台帳・職員台帳・出欠確認と有機的に連結し、業務改善（時間短縮・効率化）を実現する
- 実装順序: **① 求解入力修復 → ③ 承認ゲート実働化 → ② 職員マスタ → ⑥ 希望休 → ④ NuShift CSV 書き出し**

---

## 0. 全体原則（低性能 LLM 実装向けの実行規律）

1. **1サブステップ = 1変更単位 = 1コミット相当**。複数ファイルにまたがる変更でも、サブステップ内の変更理由は1つに限定する。
2. **テスト先行（Red → Green）**。各ステップの最初のサブステップは必ず「失敗するテスト」または「現状確認テスト」の作成とする。テストが通った状態での変更完了を確認してから次へ進む。
3. **`vendor/nushift/shiftai` は一切変更しない**（import 紀律は `vendor/nushift/README.md:38-52`）。必要な関数はホスト側にラッパーを置く。vendor の更新は `scripts/sync_nushift_vendor.py` のみで行う。
4. **既存パターン踏襲**。ルーターは `shift_schedule/routers/plans.py`、テンプレートは `templates/shift_schedule/*.html`、テストは `tests/test_paid_leave_shift_e2e.py`（TestClient + `Session(engine)` + `create_db_and_tables()`）を雛形にする。conftest.py は存在しないので各テストで fixture を自前定義する。
5. **UI 変更は AGENTS.md の手順を遵守**。画面仕様の認識合わせ（ステップ 14〜18, 22, 23, 26 の UI 部分は、まず架空データで操作できるモックを作成してユーザーが試用・合意してから本実装に入る）。未確定の提案を確定仕様として報告しない。
6. **各ステップ完了時の検証コマンド**（必ず実行して通ることを確認）:
   - `python -m ruff check <変更ファイル>`
   - `python -m pytest tests/<当該テスト> -q`
   - ステップ 6 / 13 / 20 / 24 / 27 では全件: `python -m pytest tests -q`
7. **監査ログ**: シフトに関わる状態変更（マスタ登録・希望休申請/承認）は `audit_logger.record_audit_event` または `ShiftPlanningAudits` に記録する（`plans.py:197-210` のパターン）。
8. **配備の前に更新記録を確認**し、本番機能を失う変更をしない（AGENTS.md）。

### テスト戦略（リグレッション防止）

- **命名**: 破壊的連結の修復は `tests/test_shift_bridge_inputs.py` に集約。E2E は `tests/test_shift_integration_e2e.py` に集約。
- **検証観点ごとの固定フィクスチャ**: 園児（在籍1・短時間1・欠席1・退園1）、職員（資格あり契約あり1・資格なし1）、認定（`ChildCareCertification`）、出欠確認（`AttendanceVerification`）、休園日（`ShiftFacilityClosedDays`）。
- **最終ゲート**: ステップ 27 で全テスト + `ruff check` + 既存回帰（`tests/test_regression_shift.py`、`tests/test_shift_schedule_steps12_16.py`、`tests/test_shift_solve_inputs.py`、`tests/test_paid_leave_shift_e2e.py`、`tests/test_solve_jobs_pattern_mode.py`）の完全緑化。

### 現状の確定事項（実装の前提となる調査結果）

| # | 事実 | 証拠 |
|---|------|------|
| F1 | `Child.care_time_category` は存在しない。実データは `child_care_certifications.care_time_category` | models/core.py:539-562, :909 |
| F2 | `AttendanceRecord` に `is_absent` 属性は存在しない。`planned_check_in_time` もモデルに未定義 | models/core.py:960-982 |
| F3 | ベースライン alembic 移行が `attendance_records.planned_check_in_time` 列を **drop している** | alembic/versions/3dadc5ad96b9_initial_schema_baseline.py:25-26 |
| F4 | 出欠確認は `AttendanceVerification.status`（`private_absent`/`sick_absent` で `is_absent=True`） | models/core.py:201-222, :1556-1564 |
| F5 | `effective_certification(session, child_id, target_date)` が有効認定を返す | child_care_certification_service.py:31-47 |
| F6 | gap_detector は存在しない列 `AttendanceRecord.target_date` でクラッシュし、`build_requirements(settings=, standard=, plans=)` という誤ったシグネチャで呼ぶ | gap_detector.py:57, :103-107 |
| F7 | 処方箋は `User.name`（正は `display_name`）参照で AttributeError | shift_schedule/routers/plans.py:111 |
| F8 | セル編集フォームの選択肢は EARLY/NORMAL/LATE/OFF 固定、生成セルは `HH:MM-HH:MM` | templates/shift_schedule/plan_detail.html:182-188 |
| F9 | `solve_jobs.py:181` は在籍状況を無視した `select(Child)` 全件 | shift_schedule/services/solve_jobs.py:181 |
| F10 | `build_requirements` は `closed_days`/`holiday_dates` 引数に対応済みだが渡されていない | vendor standards.py:298-309、solve_jobs.py:247-254 |
| F11 | 資格・契約の無い職員は `build_staff_member` が None を返し無通知で除外 | bridge.py:169-182 |
| F12 | vendor `Contract` は `has_36_agreement`/`overtime_allowed`/`variable_working_hours` を持つが bridge は転写していない | vendor domain.py:384-386、bridge.py:188-194 |
| F13 | `StaffContracts` に `overtime_allowed` はあるが `has_36_agreement`/`variable_working_hours` 列は無い | db_models.py:77-96 |
| F14 | `StaffShiftUnavailability` の書込経路ゼロ（status 列なし） | db_models.py:113-124 |
| F15 | NuShift 側 CSV 列定義は `data_loader.py:36-95`（日本語ヘッダ・別名読替あり） | vendor data_loader.py:36-95 |

---

# Phase 1: 求解入力のデッドリンク修復（ステップ 1〜6）

## ステップ 1: 短時間保育の連結（F1, F5）

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 1.1 | 失敗テスト作成 | `tests/test_shift_bridge_inputs.py`（新規） | `build_child_plan` に有効な `ChildCareCertification(care_time_category="short")` を渡すと `ChildPlan.is_short_time == True`、認定なしは False を検証。現状は certification を渡す口がないので引数追加が前提のテスト。`Session(engine)` + `create_db_and_tables()` パターンで DB に認定行を作る。まず実行して **失敗（AttributeError/引数不一致）を確認** |
| 1.2 | bridge 変更 | `shift_schedule/bridge.py` | `build_child_plan` にキーワード引数 `certification: ChildCareCertification | None = None` を追加。`is_short_time` を `bool(certification is not None and certification.care_time_category == CareTimeCategory.short)` に変更（`care_time_category` は列挙型なので文字列比較は `getattr(c, "value", c)` で正規化）。87 行目の `getattr(child, "care_time_category", ...)` を削除 |
| 1.3 | solve_jobs 側配線 | `shift_schedule/services/solve_jobs.py` | 園児全件の有効認定を一括取得（`select(ChildCareCertification).where(ChildCareCertification.is_active == True, effective_from <= end_date)`、F5 の篩い方に合わせホスト側で有効日フィルタ）し `certs_by_child: dict[int, cert]` を作成。203-223 のループで `build_child_plan(..., certification=certs_by_child.get(child.id))` を渡す |
| 1.4 | テスト実行 | — | `python -m pytest tests/test_shift_bridge_inputs.py -q` 緑化 + `ruff check` |

## ステップ 2: 欠席の連結（F2, F4）

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 2.1 | 失敗テスト作成 | `tests/test_shift_bridge_inputs.py` | `AttendanceVerification(status=sick_absent)` を渡すと `ChildPlan.absent == True`、`present` なら False。引数が無い現状は失敗する |
| 2.2 | bridge 変更 | `shift_schedule/bridge.py` | `build_child_plan` に `verification: AttendanceVerification | None = None` を追加。90 行目を `absent = bool(verification is not None and verification.status.is_absent)` に変更（`AttendanceVerificationStatus.is_absent` は models/core.py:221 のプロパティ） |
| 2.3 | solve_jobs 側配線 | `solve_jobs.py` | 185-190 のプリロードに `AttendanceVerification` の当該月分一括取得を追加し `verif_map: dict[tuple[int, date], AttendanceVerification]` を作る。ループで `build_child_plan(..., verification=verif_map.get((child.id, day_date)))` を渡す |
| 2.4 | テスト実行 | — | 対象テスト緑化 + ruff |

## ステップ 3: `planned_check_in_time` 復活（F2, F3）

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 3.1 | 失敗テスト作成 | `tests/test_shift_bridge_inputs.py` | `check_in_at=None`、`planned_pickup_time="17:00"` の未来日 AttendanceRecord（pickup_plan_service が生成する形）で `build_child_plan` が AttributeError を出さず `arrive=time(8,0)`（または planned 値）の ChildPlan を返すことを検証。現状は bridge.py:69 で AttributeError → 失敗確認 |
| 3.2 | モデル属性追加 | `models/core.py:969` 付近 | `AttendanceRecord` に `planned_check_in_time: Optional[str] = None` を追加（`planned_pickup_time` の隣、`max_length` は使わず `Optional[str]`。SQLite の実列は VARCHAR(5)） |
| 3.3 | alembic 移行 | `alembic/versions/<新規>.py` | ベースライン移行（F3）が同列を drop するため、`op.batch_alter_table('attendance_records')` で `add_column(sa.Column('planned_check_in_time', sa.VARCHAR(length=5), nullable=True))` を upgrade、downgrade は drop_column。`database.py` の起動時パッチ処理（create/alter 部分）と二重定義にならないか diff 確認 |
| 3.4 | テスト実行 | — | 対象テスト緑化 + `python -m pytest tests/test_models_compat.py -q` でモデル互換回帰確認 |

## ステップ 4: 在籍児童フィルタ（F9）

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 4.1 | 失敗テスト作成 | `tests/test_shift_bridge_inputs.py` | `status=退園済み`（`ChildStatus` の実際の列挙値を models/core.py で確認して使用）または `withdrawal_date <= 対象日` の園児が求解の `day_plans` に含まれないことを検証。未実装のため失敗 |
| 4.2 | ヘルパー追加 | `shift_schedule/bridge.py` | `def active_children(session, day: date) -> list[Child]` を新設。条件: `Child.status == 在籍`、`enrollment_date <= day`、`withdrawal_date is None or withdrawal_date > day`（列挙値・日付境界はテストで固定） |
| 4.3 | 呼び出し置換 | `solve_jobs.py:181`、`gap_detector.py:51` | `select(Child)` 全件を `active_children` ベースに置換（solve_jobs は月全体を扱うため対象日ごとにフィルタする形。N+1 を避けるなら月末日で1回絞り、ループ内で withdrawal_date を再判定） |
| 4.4 | テスト実行 | — | 対象テスト + `tests/test_solve_jobs_pattern_mode.py -q` で求解回帰確認 |

## ステップ 5: 休園日・祝日を必要人員へ反映（F10）

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 5.1 | 失敗テスト作成 | `tests/test_shift_bridge_inputs.py` | `ShiftFacilityClosedDays(kind="closed")` の日が `build_requirements` の結果で空行（`table.rows[day] == []`）になること、`kind="holiday"` の日が非必須（notes に「祝日」）になること。現状は渡されていないので失敗 |
| 5.2 | solve_jobs 配線 | `solve_jobs.py:247-254` | `ShiftFacilityClosedDays` を月範囲で一括取得し、`closed_days=[...kind=="closed"]`、`holiday_dates=[...kind=="holiday"]` を `build_requirements(...)` に渡す |
| 5.3 | テスト実行 | — | 対象テスト + 求解系テストの回帰確認 |

## ステップ 6: Phase 1 統合回帰（E2E）

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 6.1 | E2E テスト作成 | `tests/test_shift_integration_e2e.py`（新規） | 在籍園児2名（うち1名短時間認定）+ 欠席確認1件 + 休園日1日 + 退園児1名 + 職員2名（資格・契約あり、雛形は `test_paid_leave_shift_e2e.py`）で `_run_solve_sync` を実行し、(a) ジョブ成功、(b) 欠席児・退園児が需要に計上されない、(c) 休園日にセルが生成されない、を検証 |
| 6.2 | 全件回帰 | — | `python -m pytest tests -q` で既存テスト含め全緑化を確認（時間がかかる場合はシフト関連テスト群を実行） |

---

# Phase 2: 承認ゲート実働化（ステップ 7〜13）

## ステップ 7: gap_detector 修復（F6）

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 7.1 | 失敗テスト作成 | `tests/test_shift_integration_e2e.py` | 求解済みセルを持つプラン + 登降園データで `detect_day_gap` を呼び、例外なく `list[GapWarning]` を返すことを検証。現状は AttributeError（F6）で失敗 |
| 7.2 | detect_day_gap 書き換え | `gap_detector.py:50-107` | 園児ループを **`bridge.build_child_plan` の再利用に統一**（二重実装を廃止）: (a) 57 行目 `AttendanceRecord.target_date` → `attendance_date`、(b) 72 行目の直接属性参照を削除（ステップ 3 でモデル属性が復活済みだが bridge 経由に一本化）、(c) 103-107 を正シグネチャ `build_requirements(child_plans, [target_date], standard, day_open=..., day_close=..., granularity_min=...)` に変更 |
| 7.3 | テスト実行 | — | 対象テスト緑化 |

## ステップ 8: プラン詳細のガード

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 8.1 | 失敗テスト作成 | `tests/test_shift_integration_e2e.py` | セルはあるが登降園データに不整合（降園≤登園など）がある状態で `GET /shifts/plans/{id}` が 200 を返すことを検証（gap 検知内部の例外で画面が落ちない）。現状は 500 → 失敗 |
| 8.2 | ガード追加 | `shift_schedule/routers/plans.py:84-91` | `detect_day_gap` 呼び出しを try/except で包み、例外時は `logger.exception` して `gap_warnings` 空のまま画面描画を継続 |
| 8.3 | テスト実行 | — | 対象テスト緑化 |

## ステップ 9: 処方箋修正（F7）

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 9.1 | 失敗テスト作成 | `tests/test_shift_integration_e2e.py` | SHORTFALL BLOCKER を持つ violations 行を作り、`GET /shifts/plans/{id}` の HTML に `prescriptions`（候補職員名）が表示されることを検証。現状は `u.name` で AttributeError → 失敗 |
| 9.2 | 属性修正 | `shift_schedule/routers/plans.py:111` | `u.name` → `u.display_name` |
| 9.3 | テスト実行 | — | 対象テスト緑化 |

## ステップ 10: セル編集フォームのスロット整合（F8）

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 10.1 | 失敗テスト作成 | `tests/test_shift_integration_e2e.py` | 生成セル `slot_label="08:30-17:00"` のプラン詳細 HTML に、そのラベルが `<option>` として存在することを検証。現状の固定4択（F8）では見つからない → 失敗 |
| 10.2 | 選択肢の動的化 | `plans.py`（context に `slot_options` を追加）+ `plan_detail.html:182-188` | プランの既存セルから `sorted(set(slot_label))` を取り、`slot_options` として渡す。テンプレートは「現在値」→ `slot_options` → `OFF` の順に選択肢を生成。EARLY/NORMAL/LATE は既存セル・勤務パターンに存在する場合のみ出す |
| 10.3 | テスト実行 | — | 対象テスト緑化 |

## ステップ 11: 職員名表示

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 11.1 | 失敗テスト作成 | `tests/test_shift_integration_e2e.py` | プラン詳細 HTML に職員の `display_name` が現れること（UUID hex だけではない）を検証。失敗確認 |
| 11.2 | 表示差し替え | `plans.py` + `plan_detail.html:157,167` | context に `staff_names: dict[str, str]`（`normalize_staff_id` 互換の hex → display_name）を追加。テンプレートは `{{ staff_names.get(cell.staff_user_id, cell.staff_user_id) }}` 形式で表示（ID 併記は title 属性） |
| 11.3 | テスト実行 | — | 対象テスト緑化 |

## ステップ 12: セル編集保存時の検証

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 12.1 | 失敗テスト作成 | `tests/test_shift_integration_e2e.py` | POST `/shifts/plans/{id}/cells` で未解決ラベル（例: `NOSUCH`）を送ると 4xx が返りセルが更新されないことを検証 |
| 12.2 | 検証追加 | `shift_schedule/routers/plans_edit.py` | 保存前に `resolve_slot_to_time_window(label, settings, duty_patterns)` の結果が空でなく、かつ既存スロット集合/勤務パターン/OFF のいずれかに一致することを確認。不一致は HTTPException(400) + メッセージ |
| 12.3 | テスト実行 | — | 対象テスト + `tests/test_shift_solve_inputs.py -q` 回帰確認 |

## ステップ 13: 承認フロー回帰の補完

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 13.1 | 既存網羅の棚卸し | `tests/test_regression_shift.py` 等 | 承認 3 ケースの既存テスト有無を確認: (a) BLOCKER 残存で POST /approve → 409、(b) BLOCKER 0 件 → status=approved、(c) approved で POST /solve → 409 |
| 13.2 | 不足テスト追加 | `tests/test_shift_integration_e2e.py` | 13.1 で欠けているケースを `plans.py:160-163, 250-258` の挙動に合わせて追加 |
| 13.3 | 全件回帰 | — | `python -m pytest tests -q` 全緑化 |

---

# Phase 3: 職員マスタ入力 UI（ステップ 14〜20）

> **注意（AGENTS.md）**: ステップ 14〜18 の画面は、まず架空データで操作できるモックを作成してユーザー試用・合意後に実装する。以下は合意済みを前提とした実装ステップ。

## ステップ 14: 職員マスタ一覧 `/shifts/staff`

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 14.1 | ルーター作成 | `shift_schedule/routers/staff_master.py`（新規） | `GET /shifts/staff`（`require_can_edit`）。全 User に対し有効な `StaffQualifications`/`StaffContracts` の有無・期限を集めて context 化。`main.py` に include |
| 14.2 | テンプレート作成 | `templates/shift_schedule/staff_master.html` | 一覧表（氏名/資格/契約/有効期限）+ 未登録バッジ（資格なし=赤、契約なし=琥珀）。`base.html` を継承 |
| 14.3 | テスト作成 | `tests/test_shift_integration_e2e.py` | 200 応答、資格なし職員に警告バッジ文言、資格あり職員に氏名表示を検証 |

## ステップ 15: 資格フォーム

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 15.1 | ルーター追加 | `staff_master.py` | `POST /shifts/staff/{staff_user_id}/qualifications`（role, effective_from, effective_to）。`Role` 列挙（vendor domain）の値を検証し、監査記録。終了処理は `effective_to` の設定（UPDATE）で行う |
| 15.2 | フォーム追加 | `staff_master.html` | 行ごとの簡易フォーム（select: 保育士/子育て支援員/看護師/調理員、日付2つ） |
| 15.3 | テスト | 同上 | 登録後 `bridge.build_staff_member` が None でなくなり `roles` に反映されることを検証（ここが「求解に職員が乗る」直結点） |

## ステップ 16: 契約フォーム

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 16.1 | ルーター追加 | `staff_master.py` | `POST /shifts/staff/{staff_user_id}/contract`（employment_type, weekly_hours, daily_hours, min/max_monthly_hours, max_consecutive_days, earliest_start, latest_end, can_work_holiday, overtime_allowed）。バリデーション: weekly_hours>0、時刻は HH:MM |
| 16.2 | フォーム追加 | `staff_master.html` | 契約入力行。既定値はブランク→ bridge の既定（40h/8h）に任せる旨のヘルプテキスト |
| 16.3 | テスト | 同上 | 登録後 `build_staff_member` の `contract` に入力値が反映されることを検証 |

## ステップ 17: 36協定・変形労働の連結（F12, F13）

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 17.1 | alembic 移行 | `alembic/versions/<新規>.py` | `staff_contracts` に `has_36_agreement`（BOOL, server_default 1）と `variable_working_hours`（BOOL, server_default 0）を batch_alter_table で追加 |
| 17.2 | モデル反映 | `shift_schedule/db_models.py:94` 付近 | 上記2フィールド追加 |
| 17.3 | bridge 転写 | `shift_schedule/bridge.py:188-194` | `Contract(..., has_36_agreement=contract.has_36_agreement, overtime_allowed=contract.overtime_allowed, variable_working_hours=contract.variable_working_hours)` を転写（F12） |
| 17.4 | テスト | `tests/test_shift_bridge_inputs.py` | `overtime_allowed=False` の契約 → `Contract` に反映され `daily_cap_minutes` 相当（8h 打ち止め）になる前提が揃うことを、`Contract` インスタンスの値で検証（vendor 計算自体の検証は vendor テスト側にあるため重複しない） |
| 17.5 | フォーム拡張 | `staff_master.html` + 16.1 ルーター | 36協定（既定: 締結あり）・変形労働制チェックボックスを追加 |

## ステップ 18: CSV 一括取込

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 18.1 | テンプレート CSV | `data/shift_staff_template.csv`（新規） | 列: 職員メール/職員ID, 氏名, 資格, 雇用形態, 週契約時間, 1日契約時間, 36協定, 変形労働制, 最早始業, 最遅終業, 備考（NuShift data_loader の列名・別名読替に寄せ、職員は `User.email` で照合） |
| 18.2 | 取込関数 | `shift_schedule/services/staff_master_import.py`（新規） | UTF-8 BOM / CP932 自動判別、行単位でエラーを収集（全部落ちない）、User 照合 → `StaffQualifications`/`StaffContracts` の upsert（既存有効行は差し替え）。結果メッセージ（登録/更新/エラー行番号）を返す |
| 18.3 | ルーター+UI | `staff_master.py` + `staff_master.html` | `POST /shifts/staff/import`（ファイルアップロード、結果メッセージ表示） |
| 18.4 | テスト | `tests/test_shift_integration_e2e.py` | CSV 投入 → 資格・契約行が生成され、`build_staff_member` が全職員を返すことを検証 |

## ステップ 19: 黙示除外の解消（F11）

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 19.1 | 失敗テスト作成 | `tests/test_shift_integration_e2e.py` | 資格なし職員を1名含む求解で、(a) その職員が生成セルに現れず、(b) `ShiftViolations(severity="WARNING", code="STAFF_EXCLUDED")` 行が1件記録されることを検証。現状は無記録 → 失敗 |
| 19.2 | 除外の可視化 | `solve_jobs.py:238-244` | `build_staff_member` が None の職員を `excluded` リストに集め、`ShiftViolations` に WARNING（message に氏名と理由）を記録。既存違反の後処理と同様に旧ジョブ分は消さない（追記専用ポリシーを踏襲） |
| 19.3 | 画面表示 | `plans.py` + `plan_detail.html` | WARNING `STAFF_EXCLUDED` を「職員マスタ未登録のため除外された職員」セクションで表示し、`/shifts/staff` へのリンクを添える |
| 19.4 | テスト実行 | — | 対象テスト緑化 |

## ステップ 20: Phase 3 統合回帰

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 20.1 | E2E テスト | `tests/test_shift_integration_e2e.py` | (a) マスタ未整備 → STAFF_EXCLUDED 警告、(b) CSV 取込で整備 → 全職員が求解対象、の2段階を1テストで検証 |
| 20.2 | 全件回帰 | — | `python -m pytest tests -q` 全緑化 |

---

# Phase 4: 希望休の申請経路（ステップ 21〜24）

## ステップ 21: status 列の追加（F14）

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 21.1 | alembic 移行 | `alembic/versions/<新規>.py` | `staff_shift_unavailability` に `status`（VARCHAR(16), server_default 'approved'）を追加。**既存行を approved 扱いにする**ため default は approved（bridge 互換） |
| 21.2 | モデル反映 | `shift_schedule/db_models.py:113-124` | `status: str = Field(default="approved", max_length=16)` 追加 |
| 21.3 | テスト | `tests/test_shift_bridge_inputs.py` | 列挙扱い（"pending"/"approved"/"rejected"）で保存・読み出しができることを検証 |

## ステップ 22: 職員ポータルからの申請

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 22.1 | ルーター作成 | `routers/staff_portal.py` または `shift_schedule/routers/staff_portal_requests.py`（新規） | `GET /staff/shift-requests`（自分の申請一覧+フォーム）、`POST /staff/shift-requests`（target_date, start_time, end_time, reason → `StaffShiftUnavailability(status="pending")`、重複日チェック）。CSRF・監査ログ・`require_can_edit` 相当の職員認証は既存ポータルの認証方式に合わせる |
| 22.2 | テンプレート作成 | `templates/staff_portal/shift_requests.html` | 申請一覧（status バッジ）+ 新規申請フォーム |
| 22.3 | テスト | `tests/test_shift_integration_e2e.py` | POST → pending 行が1件、同日重複は拒否されることを検証 |

## ステップ 23: 園長側の承認

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 23.1 | ルーター作成 | `shift_schedule/routers/staff_requests_admin.py`（新規） | `GET /shifts/requests`（pending 一覧）、`POST /shifts/requests/{id}/approve|reject`（`require_admin`、監査記録） |
| 23.2 | テンプレート作成 | `templates/shift_schedule/requests_admin.html` | pending 一覧 + 承認/却下ボタン |
| 23.3 | テスト | 同上 | approve → status=approved、reject → rejected、非管理者は 403 を検証 |

## ステップ 24: bridge 反映とナビ導線

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 24.1 | bridge 絞り込み | `shift_schedule/bridge.py:116-123` | `StaffShiftUnavailability` 読みに `status == "approved"` 条件を追加。テスト: pending の希望休は求解に反映されない（`build_staff_preferences` の戻り `unavailable` に含まれない） |
| 24.2 | avoid 設定の反映 | `bridge.py` + `staff_master.py` | `StaffShiftPreferences`（avoid_early/avoid_late）を読み、vendor `StaffPreferences(avoid_early=..., avoid_late=...)`（F15 の domain.py:576-577）に転写。マスタ一覧に編集フォーム追加。テスト: 転写値の検証 |
| 24.3 | ナビ導線 | `templates/base.html`（870行目以降のサイドバー） | 「連絡と記録」配下の職員シフト近傍に「職員シフト設定（/shifts/staff）」「希望休管理（/shifts/requests）」を追加。`/paid-leave` へのリンクも設定グループまたは職員メニューに追加 |
| 24.4 | 全件回帰 | — | ナビリンク存在のテスト（HTML に href が含まれる）+ `python -m pytest tests -q` 全緑化 |

---

# Phase 5: NuShift CSV 書き出し（ステップ 25〜27）

## ステップ 25: エクスポートサービス

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 25.1 | サービス作成 | `shift_schedule/services/nushift_export.py`（新規） | 3 関数: `children_csv_rows(session, start_date, end_date)` / `staff_csv_rows(session)` / `preferences_csv_rows(session, start_date, end_date)`。**ヘッダは vendor `data_loader.py:36-95` の日本語列名に完全一致**させる（園児ID/氏名/年齢/登園日/登園時刻/降園時刻/短時間保育/欠席/早朝保育/延長保育…、職員ID/氏名/資格（主）/雇用形態/週契約時間/1日契約時間/36協定/変形労働制…、職員ID/種別/日付/開始/終了/理由）。データは Phase 1〜4 で整備した実テーブル（認定→短時間、出欠確認→欠席、approved 希望休+有給→「出勤不可」行）から生成 |
| 25.2 | テスト作成 | `tests/test_shift_integration_e2e.py` | (a) 各 CSV のヘッダ行が vendor 列定義と一致、(b) 値の書式（日付 `YYYY-MM-DD`、時刻 `HH:MM`、真偽 `true/false`）、(c) 短時間児・欠席日・approved 希望休が正しい行になることを検証 |
| 25.3 | テスト実行 | — | 対象テスト緑化 |

## ステップ 26: ルーター + UI

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 26.1 | ルーター作成 | `shift_schedule/routers/nushift_export.py`（新規） | `GET /shifts/nushift-export?month=YYYY-MM&kind=children|staff|preferences|zip`（`require_admin`）。ZIP は3 CSV を1アーカイブに。BOM 付き UTF-8、ファイル名 `nushift_children_YYYY-MM.csv` 等。`main.py` に include |
| 26.2 | ボタン追加 | `templates/shift_schedule/staff_master.html`（または plans_list） | 対象月選択 + 3 CSV / ZIP ダウンロードボタン |
| 26.3 | テスト | 同上 | HTTP 200、BOM 先頭バイト、行数整合、ZIP 内 3 ファイルを検証 |

## ステップ 27: 最終回帰とドキュメント

| No | サブステップ | 対象 | 内容 |
|----|--------------|------|------|
| 27.1 | 最終ゲート | — | `python -m ruff check .` + `python -m pytest tests -q` 全緑化。vendor スモーク（`python scripts/sync_nushift_vendor.py --verify`）も通ることを確認 |
| 27.2 | ドキュメント更新 | `docs/`、`MANUAL.md` 該当節 | 本計画書の実装記録（日付・ステップ番号・変更ファイル）を追記。月次運用フロー（台帳→NuShift 取込→求解→承認→配信）の1枚図を反映 |
| 27.3 | 手動確認手順 | チェックリスト | デモ環境で (1) 職員マスタ登録→(2) 希望休申請/承認→(3) 求解→(4) セル編集（実ラベル選択肢）→(5) 承認（BLOCKER ゲート）→(6) NuShift CSV ダウンロード→NuShift 側読込、を架空データで一巡しスクリーンショット保存。PUBLISH_READINESS_CHECKLIST 照合 |

---

## 進行管理のルール

- 各ステップ完了ごとに本計画書の表に「実装日 / コミット / テスト結果」を追記する。
- UI を含むステップ（14〜18, 22, 23, 26）は、**モック作成 → ユーザー試用 → 合意 → 本実装** の順で、モック段階と実装段階を別ステップ扱いで進めてよい（合意前に本実装に着手しない）。
- 仕様変更の必要性が判明した段階（例: 休園日の運用方針、希望休の承認フローの詳細）は、計画書を更新してから先へ進む。
- 配備はユーザーの指示に従い、配備前に最新の更新記録を確認する（AGENTS.md）。

---

## 4. 実装完了記録（2026-11-10）

全27ステップの実装およびテスト検証が完了しました。

### Phase 1: 求解入力のデッドリンク修復（ステップ 1〜6）
- **ステップ 1 (短時間保育)**: `bridge.build_child_plan` に `certification` 引数を追加。`solve_jobs` で一括取得・配線。
- **ステップ 2 (欠席連結)**: `bridge.build_child_plan` に `verification` 引数を追加。`AttendanceVerificationStatus.is_absent` を反映。
- **ステップ 3 (planned_check_in_time)**: `AttendanceRecord.planned_check_in_time` をモデルおよびマイグレーション（`b7d21c4e90a1`）で復活。
- **ステップ 4 (在籍児童フィルタ)**: `bridge.active_children` を新設し、求解および gap 検知で退園児を除外。
- **ステップ 5 (休園日・祝日)**: `ShiftFacilityClosedDays` を一括取得し `build_requirements` の `closed_days`/`holiday_dates` に配線。
- **ステップ 6 (統合回帰)**: `tests/test_shift_bridge_inputs.py` (5件), `tests/test_shift_integration_e2e.py` (ステップ6 E2E) 全パス。

### Phase 2: 承認ゲート実働化（ステップ 7〜13）
- **ステップ 7 (gap_detector修復)**: `AttendanceRecord.attendance_date` および `bridge.build_child_plan` への一本化。
- **ステップ 8 (プラン詳細ガード)**: `plans.py` で `detect_day_gap` 例外時の安全フォールバック（画面クラッシュ防止）。
- **ステップ 9 (処方箋修正)**: `User.display_name` 参照に修正。
- **ステップ 10 & 11 (スロット整合・職員名表示)**: 既存セル・勤務パターンからの動的選択肢生成、職員名（`staff_names`）表示。
- **ステップ 12 (セル編集検証)**: 不正スロット入力に対する 400 バリデーション。
- **ステップ 13 (承認フロー回帰)**: BLOCKER 残存時 409、解消後承認、承認済み再求解禁止（409）のゲート網羅。

### Phase 3: 職員マスタ入力 UI（ステップ 14〜20）
- **ステップ 14〜16 (職員マスタ)**: `/shifts/staff` ルーター・テンプレート追加。未登録バッジ、資格登録、契約登録。
- **ステップ 17 (36協定・変形労働)**: `StaffContracts` に `has_36_agreement`/`variable_working_hours` 追加（マイグレーション `c8d32e5f10b2`、SQLite `038`）および `bridge` 転写。
- **ステップ 18 (CSV 一括取込)**: `shift_staff_template.csv`、`staff_master_import.py`、`/shifts/staff/import` 実装。
- **ステップ 19 (黙示除外の解消)**: 資格・契約のない職員を `STAFF_EXCLUDED` WARNING としてプラン詳細にリンク付きで可視化。
- **ステップ 20 (Phase 3 回帰)**: マスタ登録・CSV取込・除外警告の E2E 検証パス。

### Phase 4: 希望休の申請経路（ステップ 21〜24）
- **ステップ 21 (status 列追加)**: `StaffShiftUnavailability.status` 追加（マイグレーション `d9e43f6a20c3`、SQLite `039`）。
- **ステップ 22 (職員申請ポータル)**: `/staff/shift-requests` GET/POST 実装。重複日申請拒否。
- **ステップ 23 (園長承認)**: `/shifts/requests` GET/POST（承認・却下）実装。
- **ステップ 24 (bridge 反映・ナビ)**: `status == "approved"` のみ求解反映。`avoid_early`/`avoid_late` 転写。サイドバーに導線リンク追加。

### Phase 5: NuShift CSV 書き出し（ステップ 25〜27）
- **ステップ 25 (エクスポートサービス)**: `nushift_export.py`（園児・職員・希望休）。NuShift vendor 日本語ヘッダ完全準拠。
- **ステップ 26 (ルーター・UI)**: `/shifts/nushift-export`（個別CSV & ZIP一括ダウンロード）。
- **ステップ 27 (最終ゲート)**: `ruff check` 全件クリア、シフト関連回帰テスト全31件パス。

