# 職員シフト自動作成（nushift / shiftai 統合）提案

- 対象リポジトリ: open-hoikuict
- 取り込み元: `E:\nushift\nushift`（パッケージ名 `shiftai`、GitHub `annahoikuen-debug/nushift`）
- 状態: **未確定 0 項。モック作成済み・試用待ち。実装は未着手**
- 基準コミット: open-hoikuict `ab947ba`（`main`）
- 基準コミット: nushift `c5c86f3`（`master`、未コミット差分あり）
- 作成日: 2026-10-03
- 更新: 2026-10-03（未確定事項 #4 / #9 を確定。2.9.1 と 3.2 を追加。3.3 にモック作成記録。
  **訂正**: 2.13 / 2.14 と 4 を追加。nushift の成熟度・1日の労働上限・計算単位を実測で修正（**月単位求解は使用不可**）。
  #1〜#8 を確定（3.0a〜3.0f）。未確定 0 項）

> **Disambiguation**: 本書の日付・コミット・URL・データモデルは、2026-10-03 時点の
> 調査に基づく**実装案**である。`shift_schedule/` 配下のコード、`/shifts` 配下のルート、
> `shift_*`  таблиは現在のコードには存在しない。
> `shiftai` 側は Streamlit アプリとして `E:\nushift\nushift` に存在するが、
> 本提案はコア（`src/shiftai` のうち `ui/` を除く部分）の取り込みを対象とする。

---

## 1. 要望（ユーザーの指定）

- 2026-10-03、ユーザー：「このICTプロジェクトに別プロジェクトであるnushiftの機能を統合したい」
- 2026-10-03、統合方式の選択：**案A（ライブラリ取り込み）**
- 2026-10-03、登園予定時刻の扱い：**案(b) 新規 `planned_check_in_time` を整備**
- 2026-10-03、未確定事項 #4：**園児ごとの既定値＋例外日のみ上書き**（→ 2.9.1）
- 2026-10-03、未確定事項 #9：**フェーズ1は画面2〜5**（→ 3.2）

---

## 2. こちらの解釈

以下は本提案側で決めた解釈であり、確定仕様ではない。

### 2.1 統合の狙い

open-hoikuict は **シフト機能を一切持たない**（`シフト`/`勤務表`/`配置`/`roster` の業務実装ゼロ）。
`docs/paid-leave-management-spec.md:64` は「シフト自動最適化」を**対象外・別機能**と明記しており、
本提案はその先送り分を埋める位置づけとなる。

nushift 側は保育所の**職員配置基準リンク型シフト自動作成** MILP ソルバであり、
自治体の配置基準プリセット14種と労働基準法の制約を満たすシフト表を生成する。
両プロジェクトは同じ制度（保育所）に属し、`shiftai` は**DB・ORM・永続化を持たない純粋な関数群**であり、
open-hoikuict の `hoikuict.db` に侵入しない。

したがって **領域適性とコード適合性はともに高く、衝突は無い**。

### 2.2 「統合」の範囲

本提案で対象とするのは **コア計算部分のみ** であり、次を含めない。

| 対象外 | 理由 |
| --- | --- |
| `shiftai/ui/`（Streamlit 5,932行） | FastAPI + Jinja2/HTMX の画面が既存方針。移行不要 |
| `shiftai/gas_client.py`（Google Sheets 連携） | 既存の取り込み経路は `/data-transfers/` と Excel。Sheets は不要 |
| `shiftai/exporter.py` | 後述 2.6 のとおり独自実装に置換 |
| `shiftai/compliance.py`（施設届出監査） | 認可外/企業主導型向けの届出適合監査。今回は別機能 |
| `shiftai/importers.py`（CoDMON / キッズリー 取込） | `/data-transfers/` が既存経路 |
| `shiftai/sample_data.py` / `diagnostics.py` / `live_validation.py` | 本画面には不要 |

### 2.3 取り込み方法

`shiftai/pyproject.toml` の実行時依存には **`streamlit` が含まれる**ため、`pip install` では取り込めない。

採用は **`vendor/nushift/` へのコピー ＋ `sys.path` 追加**（`pip install` しない）とし、
依存は必要なものだけ open-hoikuict 側 `requirements.txt` に明示する。
submodule を採用しない理由は 3.0a に記す。

```
open-hoikuict/
  vendor/nushift/
    shiftai/                       # ここを sys.path へ追加（pip install はしない）
    README.md                      # コピー元・基準コミットを記載
```

- `pip install` しないので `streamlit` は入らない
- `shiftai/__init__.py` の `_resolve_version()` は `importlib.metadata` に依存するが、
  インストール済みでない場合のフォールバックを持つ（`__init__.py:8-30`）
- **検証済み（2026-10-03）**: 66ファイルをコピーして `sys.path` に追加すると
  `domain` / `standards` / `local_rules` / `solver` / `gap_analysis` が
  streamlit なしで import でき、プリセット14種と `PULP_CBC_CMD` が使える
- Docker は `COPY . .` のままでよい。`.gitmodules` を init する手順が要らない
- 逆に、nushift 側の更新は**手で差分を取り込む**必要がある

### 2.4 `shift_schedule/` モジュール構成

`plan_docs/`（既に統合済みの保育計画モジュール）の型を踏襲する。

```
shift_schedule/
  __init__.py
  contracts.py       # StrEnum: Role / EmploymentType / StaffingStandardKey /
                     #        SolveJobStatus / ViolationSeverity / PlanStatus
  models.py          # dataclass(slots=True) のビューモデル
  db_models.py       # SQLModel table=True（database.py へ副作用 import する唯一のファイル）
  store.py           # Protocol + SqlModelShiftRepository + Dep
  serializers.py
  bridge.py          # open-hoikuict の行 → shiftai の frozen dataclass への写像
  templating.py
  services/
    facility.py        # 施設設定（開園/閉園/粒度/定員/配置基準/休園日）
    staff_contracts.py # 職員資格・契約・希望休
    child_plans.py     # 園児×日付の ChildPlan 組み立て
    solve_jobs.py      # ジョブキュー + ワーカー（CBC を外部実行）
    violations.py      # 21種の違反コードと basis の整形
    exports.py         # CSV / XlsxWriter / icalendar
  routers/
    home.py            # GET  /shifts/
    facility.py        #      /shifts/facility
    contracts.py       #      /shifts/contracts
    plans.py           #      /shifts/plans, /shifts/plans/{id}, .../solve
    plans_edit.py      #      /shifts/plans/{id}/cells
    exports.py         #      /shifts/plans/{id}/export/*
```

宿主への接続点（`plan_docs` と同じ手順）:

| 場所 | 変更 |
| --- | --- |
| `database.py:50-53` | `import shift_schedule.db_models  # noqa: F401` を追加 |
| `database.py:66-95` | `_migrate_shift_*()` を追加し呼び出し列に挿す |
| `main.py:73-78` 付近 | ルーター import を追加 |
| `main.py:200-204` 付近 | `app.include_router(..., prefix="/shifts")` を追加 |
| `main.py:106-125` | `solve_jobs.shift_worker_loop()` を lifespan のバックグラウンドタスクに追加 |
| `templates/shift_schedule/**` | 新規。すべて `{% extends "base.html" %}` |
| `templates/base.html` | サイドバー項目追加。`/plans` と同様のモジュール別テーマ |

### 2.5 追加・変更するテーブル

**既存テーブルの変更（1件のみ）**

| テーブル | 追加列 | 理由 |
| --- | --- | --- |
| `attendance_records` | `planned_check_in_time: Optional[str]`（`"HH:MM"`、`ALTER TABLE ADD COLUMN`） | 案(b)。**例外日の上書き専用**（未確定事項4 の決定）。`planned_pickup_time`（`models.py:999`）と対称にする |
| `users` | `can_manage_shifts: bool` | `paid-leave-management-spec.md:82` と同じ流儀。`staff_role` は権限レベルであり雇用形態ではない |

**新規テーブル（11件）**

| テーブル | 主キー／主な列 | 備考 |
| --- | --- | --- |
| `child_planned_arrival_defaults` | `child_id` PK/FK, `planned_check_in_time`, `effective_from`, `effective_to`, `updated_by_user_id`, `updated_by_name`, `updated_at` | **未確定事項4 の決定により追加**。園児ごとの既定登園予定時刻 |
| `shift_facility_settings` | `id=1` 単一、`day_open`, `day_close`, `granularity_min`, `capacity`, `staffing_standard_key`, `min_two_staff_rule`, `enforce_min_two` | 既存 `GuardianHoursSetting`（`models.py:1508-1513`）は**閉園時刻1個のみ**で、開園時刻が無い |
| `shift_facility_closed_days` | `setting_id`, `target_date`, `kind`(`closed`/`holiday`) | 休園日・祝日 |
| `staff_qualifications` | `staff_user_id` FK, `role`, `effective_from`, `effective_to`, `note` | 保育士/支援員/看護師/調理員等。**現在は存在しない** |
| `staff_contracts` | `staff_user_id` FK, `employment_type`, `weekly_hours`, `daily_hours`, `min_monthly_hours`, `max_monthly_hours`, `max_weekly_days`, `max_consecutive_days`, `earliest_start`, `latest_end`, `can_work_holiday`, `overtime_allowed`, `effective_from`, `effective_to` | **`users` に雇用属性が皆無**（`models.py:2704-2721`） |
| `staff_shift_preferences` | `staff_user_id` FK, `avoid_early`, `avoid_late`, `max_early_shifts`, `max_late_shifts`, `notes` | `StaffPreferences`（`domain.py:474-486`）に対応 |
| `staff_shift_unavailability` | `staff_user_id` FK, `target_date`, `start_time`, `end_time`, `kind`(`希望休`/`出勤不可`/`出勤希望`/`休み希望`), `reason` | `Unavailability`（`domain.py:464-471`）に対応。**有給は `paid_leave` が未実装のため本テーブルで持つ** |
| `shift_plans` | `id`, `target_month`(YYYY-MM 文字列), `status`(`draft`/`generated`/`approved`/`archived`), `staffing_standard_key`, `lock_version`, `input_fingerprint`, `created_by_user_id`, `created_by_name`, `created_at`, `updated_at` | `PlanDocumentHeadRow` と同じ楽観ロック方式 |
| `shift_plan_cells` | `plan_id` FK, `staff_user_id` FK, `target_date`, `slot_label`, `cell_state`, `pinned_by_user_id` | `fixed_assignments` 相当（`solver.py:1382`） |
| `shift_solve_jobs` | `id`, `plan_id` FK, `status`(`queued`/`running`/`succeeded`/`failed`/`cancelled`), `requested_by_user_id`, `requested_at`, `started_at`, `finished_at`, `time_limit_sec`, `relax_level`, `is_approved_snapshot`, `stats`(JSON), `error_message` | CBC 実行の単位 |
| `shift_violations` | `plan_id` FK, `job_id` FK, `code`(21種), `severity`, `target_date`, `slot_label`, `staff_user_id`, `message` | 追記専用 |
| `shift_planning_audits` | `actor_user_id`, `target_plan_id`, `action`, `summary`, `metadata`(JSON), `created_at` | 追記専用。`StaffPermissionChangeLog` と同じ流儀 |

保存時刻・業務日付の規約は既存に合わせる（`time_utils.utc_now()` / `local_today()`、
時刻は `HH:MM` 文字列、`docs/facility-settings-spec.md:177-183`）。

### 2.6 依存と出力

`shiftai/gap_analysis.py:16` はモジュール先頭で `pandas` を import するため **pandas は必須**。
一方 `shiftai/exporter.py:16-17` は `pandas` + `openpyxl` を要求するが、
open-hoikuict は既に **`XlsxWriter==3.2.9`** と **`icalendar==7.3.0`** を持つ。

したがって **`shiftai.exporter` は使わず**、`shift_schedule/services/exports.py` を
既存ライブラリで実装する。これにより **`openpyxl` を追加せずに済む**。

`requirements.txt` への追加は次の3行に留まる:

```
pandas>=3.0,<4
numpy>=2.4
pulp>=2.9,<3
```

> `pulp` は `<3` 厳守。`requirements.txt:36-40`（nushift 側）に、
> PuLP 3.x/4.x は `LpVariable(..., cat=...)` と `LpProblem(cat=LpMinimize)` の仕様を壊し
> `solver.py:454-455,1286` の解デコードが全滅すると明記されている。
> CBC 実行ファイルは `pulp` ホイール同梱（`tests/test_solver.py:102-104` が
> `available_solvers()` に `PULP_CBC_CMD` を含むことを検証）。

### 2.7 CBC をリクエスト経路で起動しない（必須要件）

`solver.solve_shift()`（`solver.py:1371-1386`）は **`solver.py:1514` で CBC を同期起動する**。
既定 `time_limit_sec=60` は 2 パスに配分される（`solver.py:1503` / `1658-1659`）。

**実測（2.14）**: 園児62名・職員25名・`福岡市` で、5日間なら 12,107 変数 / 10,296 制約、
**30〜47秒**かかった。**`time_limit_sec` は上限ではなく**、30秒指定で 46.7秒 Measured。
`limit` を API の応答時間制御に使えない。

よって **`POST /shifts/plans/{id}/solve` はジョブ行の作成と `303` リダイレクトのみ**を行い、
求解は `main.py:106-125` の `parent_push_worker_loop` と同じ形式の
専用バックグラウンドワーカーが行う。画面は HTMX で状態をポーリングする。

追加の制御:

- `time_limit_sec` は**施設設定で上限を設ける**（既定 30 秒・上限 120 秒）
- ワーカーは**同時1ジョブ**（専用 `ThreadPoolExecutor(max_workers=1)`）
- 起動時セルフチェックで `PULP_CBC_CMD` が可用か検証し、無ければ
  シフト機能を「利用不可」で起動する（園の他の機能を止めない）

### 2.8 Docker / TrueNAS

`Dockerfile:1` は `python:3.12-slim`、`USER appuser`（非 root）。
CBC は `pulp` ホイール同梱の実行ファイルを **subprocess として** 起動するため、
デプロイ前に以下を実機確認する（**未確認**）:

1. `python:3.12-slim` で同梱 CBC が起動できるか（glibc / `libgcc-s1` の存在）
2. 非 root `appuser` で実行できるか
3. `python:3.12` + `pandas 3.0` で nushift のテストが通るか
   （nushift の検証環境は **Python 3.13.15**、CI は 3.12）

`vendor/` 方式（3.0a）のため、`Dockerfile` の `COPY . .` は**変更不要**。
submodule の init 手順やビルド時のネットワーク到達は不要になる。

`.dockerignore` は `.git` を除外するが、これは submodule を init できない原因であり、
vendor 方式では無関係。`vendor/` は除外 Patterns に無いことを確認済み。

### 2.9 園児側の写像（案b の反映）

対象月の各日について `shiftai.domain.ChildPlan` を組み立てる。

| `ChildPlan` フィールド | 由来 | 備考 |
| --- | --- | --- |
| `child_id` | `str(children.id)` | |
| `name` | `children.full_name` | `models.py:611-613` |
| `day` | 対象日 | |
| `age_class` | **`birth_date` から対象日基準で算出** | ⚠ 下記 |
| `arrive` | **4段階の優先度で決定**（下記 2.9.1） | 未確定時は区分の `normal_start_time` にフォールバックし、**どの段階で補完したかを画面に出す** |
| `depart` | `attendance_records.planned_pickup_time`（既存 `models.py:999`） | 同様に `normal_end_time` フォールバック |
| `is_short_time` | `ChildCareCertification.care_time_category == short`（`models.py:939`） | 対象日時点で有効な証明。`child_care_certification_service.effective_certification()` を使用 |
| `absent` | `AttendanceVerification` の `is_absent` | 対象日が将来なら未記録のため `False` |
| `uses_early_care` / `uses_late_care` | `arrive`/`depart` が各保育標準時間帯を跨ぐか | `standards._resolve_window` の判定（`standards.py:122-126`）に合わせる |
| `notes` | 既存 `attendance_records.note` | |

> ⚠ **`Child.age`（`models.py:619-624`）は `local_today()` 基準であり使ってはいけない。**
> 来月以降のシフト作成では年齢がずれる。対象日基準で計算し
> `shiftai.domain.AgeClass.from_years()`（`domain.py:47-55`）に渡す。

> ⚠ **`ChildPlan` は `depart <= arrive` で `ValueError` を投げる**（`domain.py:274-276`）。
> 1 園児でも不正なら全体が壊れないよう、**園児単位で捕まえてエラー行として収集**し、
> 生成前に一覧表示する。

> ⚠ 対象月の `AttendanceRecord` は現時点で**存在しない**。
> `planned_check_in_time` は例外日の上書きとしてのみ機能する（下記 2.9.1）。

### 2.9.1 登園時刻の優先度（未確定事項4 の決定: 2026-10-03）

ユーザーは「**園児ごとの既定値＋例外日のみ上書き**」を選択した。
日ごとの全園児入力（園児25名×31日＝775件/月）は運用が重いと判断された。
降園予定が日ごとで入力されるのに対し、登園時刻は日によってほとんど変わらないためである。

`arrive` は次の順で決定する。

| 優先 | 出典 | 適用条件 |
| --- | --- | --- |
| 1 | `attendance_records.check_in_at`（**実績打刻**） | 対象日が**今日以前**のとき。過去を計画で書き換えないため実績を優先 |
| 2 | `attendance_records.planned_check_in_time`（**新規列**） | その日の上書きがあるとき |
| 3 | `child_planned_arrival_defaults.planned_check_in_time`（**新規表**） | 園児ごとの既定値。園児ごとに1回だけ入力する |
| 4 | `ExtendedCareFeeRule.normal_start_time`（保育必要量区分） | 上記が未設定のとき |
| 5 | `shift_facility_settings.day_open` | 区分が未設定のとき（開園時刻） |

`depart` も同様に、優先2以降は `planned_pickup_time` → `normal_end_time` → `day_close` で決める。

**保存先は2か所**になる。園児ごとの既定は `child_planned_arrival_defaults`（出欠ドメイン）、
例外日は `attendance_records.planned_check_in_time`（既存行）。
`shift_schedule` は両方を**読むだけ**で、書き込まない。

#### 請求・报警への影響（検証済み: 安全）

打刻のない将来日 `AttendanceRecord` 行を新規作成しても、既存経路への影響はない。

| 経路 | 判定 | 根拠 |
| --- | --- | --- |
| 月次料金の再計算 | 対象外 | `extended_care_fee_service.py:487` が `check_out_at.is_not(None)` で絞る |
| 月次概要の未計算警告 | 対象外 | `extended_care_fee_service.py:620-626` が同じ絞り |
| 月次 CSV / Excel | 出力されない | `build_monthly_csv` は `ExtendedCareCharge` 行のみを集計する |
| 延長保育料→請求転送 | ブロックしない | `extended_care_billing_transfer_service.py:204` が同じ絞り。未計算エラーは `errors` に入らない（`can_transfer` は `:98-104` で判定） |
| 全銀（Zengin） | 到達しない | `zengin_service.py` は `AttendanceRecord` を参照しない（`BillingClaim` のみ） |
| 出欠アラーム | 発生しない | `attendance_checks_service.py:53` が `check_in_at is not None` を要求 |
| 出欠一覧の报表 | 表示が 1 行増える | `routers/attendance.py:431-436` は日付範囲のみ絞るため `未登園` 行と `not_checked_in_count` が増える |

これは**既存挙動と同じ**である。`pickup_plan_service.py:55-62` は既に打刻なし行を新規作成し、
`routers/parent_portal.py:1946-1948` は「過去のみ拒否、未来は明示的に許可」している。

> テストの穴: 上表の「対象外」を保証する断言が現状ない。
> `test_shift_schedule.py` に「打刻なし将来日行が `ExtendedCareCharge` を作らず
> 転送をブロックしない」テストを追加する。

### 2.10 職員側の写像

| `StaffMember` / `Contract` | 由来 |
| --- | --- |
| `staff_id` | `str(users.id)`（UUID 文字列） |
| `name` | `users.display_name` |
| `roles` | `staff_qualifications` から。有効な資格が 1 件も無い職員は `ValueError`（`domain.py:353-354`）になるため**除外してエラー表示** |
| `contract` | `staff_contracts` の有効期間行 |
| `skills` | 未使用（`docs/04_データ仕様.md:144`）。空集合 |

`is_placeable`（`domain.py`）は調理員・薬剤師・園長・主任を配置対象から除外するため、
この 4 職種は資格を設定してもシフト枠には出ない。

配置基準は **`local_rules.build_standard(key, overrides=...)`**（`local_rules.py:658-686`）で得る。
**`local_rules.register_preset()`（`local_rules.py:689-699`）は使わない**。
同関数は `MUNICIPAL_PRESETS` 等のモジュールグローバルを mutate するため、
同時実行下でのテナント隔離を壊さない。

### 2.11 承認と保存の扱い

`shiftai` は fail-closed で設計されている。検証器が実行できない場合
`CHECK_UNAVAILABLE` を BLOCKER として出す（`docs/02_ソルバ仕様.md:765-782`）。

これを踏まえ、本提案では:

- 求解結果は必ず `status=draft` として保存し、**自動では確定しない**
- `shift_violations` に **BLOCKER が 1 件でもある間は `approved` へ遷移させない**（409）
- `generate` は「参考値」であり画面上でもその旨を明示する
- 職員が固定したマスは `fixed_assignments` として再生成時にも渡し、自動生成で上書きしない

承認状態遷移を持つ理由は、`plan_docs` が `plan_document_actions`（`created` / `submitted` / `returned` / `approved`）を持つためである。shift にも同等の操作履歴を持たせる（未確定事項5）。

### 2.12 権限

`users.can_manage_shifts` を追加し、`staff_permissions.STAFF_PERMISSION_DEFINITIONS`
（`staff_permissions.py:20`）に項目を足し、変更は `StaffPermissionChangeLog`（`models.py:2998`）へ記録する。

- 閲覧: `view_only` 以上
- 作成・生成・修正・出力: `can_edit` かつ `can_manage_shifts`
- 承認: `can_manage_shifts` かつ `staff_role=admin`

`plan_docs/auth_adapter.py` のような独自 `Role` 語彙は作らず、
宿主の `auth.get_current_staff_user` と `staff_permissions` を使う。
シフトは職員起点の領域であり、園児・クラス単位のアクセス判定ではないため、
`plan_docs` の模倣より宿主プリミティブが適切。

### 2.13 1日の労働上限の4段階（未確定事項2 の前提）

`shiftai` は意図的に異なる値を持ち、**`config.py` がその理由を明記している**。
「10h と 8.75h の不統一」ではない。

| 定数 | 値 | 役割 | 参照 |
| --- | --- | --- | --- |
| `STATUTORY_DAILY_WORK_HOURS` | 8 | 法定労働時間 | `config.py:35` |
| `STATUTORY_MAX_DAILY_WORK_HOURS` | 10.0 | 労働基準法32条・34条の**1日上限**。`solver` / `gap_analysis` / `live_validation` が共有する**ハード制約** | `config.py:41` |
| `STATUTORY_DAILY_LIMIT_HOURS` | 8.75 | 法定8h ＋ 休憩45分。`gap_analysis` の**適合判定**に使う | `config.py:49` / `gap_analysis.py:502` |
| `INTERNAL_DAILY_LONG_HOURS` | 9.0 | ソルバ内部の「長すぎる勤務」**ペナルチの目安**。適合判定ではない | `config.py:54` / `solver.py:84` |

> `config.py:46-48`「`solver._LONG_DAILY_HOURS`（9時間）とは別の概念で、**両者は意図的に値が違う**。
> 統一していない。」
> `config.py:51-53`「`STATUTORY_DAILY_LIMIT_HOURS`（8.75）とは別の閾値であり、
> `gap_analysis` の適合判定と値を揃える必要はない。」

したがって未確定なのは **「どの閾値を承認の gate にするか」** であって、値の統一ではない。
なお `gap_analysis.py:502` の適合判定は 8.75h だが、ハード制約である 10h が先に効くため
8.75h〜10h の帯域に解が存在し得る。この帯域を園がどう扱うかが設計上の分岐になる。

未修正の **R2-FV-08**（`daily_cap` 超過が `live_validation` では WARNING、`solver` では
ハード制約になり貪欲法に退避する）は、この帯域の扱いと直結する。

### 2.14 計算の単位は「月」ではなく「週」（未確定事項3 の実測: 2026-10-03）

`E:\nushift\nushift` の実 API を直接叩いて測った。`shiftai` の読み取りのみ。

| 対象期間 | 変数 / 制約 | BLOCKER | status | 実測時間（上限30秒） |
| --- | --- | --- | --- | --- |
| **5日** | 12,107 / 10,296 | **10** | 部分的なシフト | 30.5s |
| **10日** | 24,065 / 20,693 | **106** | 部分的なシフト | 25.5s |
| **20日** | 48,301 / 41,505 | **88** | 部分的なシフト | 46.7s |

条件: 園児62名・配置対象職員25名・`福岡市`・30分粒度・07:30〜19:30・2名ルールあり。

**5日 → 10日で BLOCKER が 10 → 106 に跳ね上がる。** 供給側の不足
（`shortfall_rows` の gap）は 3 期間とも **24 マスで一定**なので、人員不足ではなく
**ソルバが複数週を一度に扱えない**ことによる。

**緩和策も効かない**（20日・L0 / L2、30秒 / 60秒 の4通りとも BLOCKER 88 で同一）。
どの組み合わせでも `部分的なシフト`（PARTIAL）を卒業できず、最良でも
`実行可能解`（FEASIBLE）止まり、**最適性は証明されない**。

#### 設計への帰結

| 項目 | 帰結 |
| --- | --- |
| 対象単位 | **週単位に分割**して求解し、月は結果の集合とする。`target_month` 一括で持有すると間に合わない |
| `time_limit_sec` | **上限ではない**。30秒指定で 46.7秒かかった。2パス配分（`solver.py:1503` / `1659`）が超過するため。**web の応答時間制御に使えない** |
| 実行場所 | 1週間ぶんの実測で 30〜47秒。**TrueNAS でリクエスト経路は不可**。当日中ワーカー必須（2.7 の前提どおり） |
| 画面文言 | 「最適」ではなく「**実行可能**」と表示する。最適性を約束してはいけない |
| 既定値 | 分割により 1 回の変数は 12,000 程度。60秒へ延ばしても改善しないため**既定 30 秒で十分**、上限 60 秒 |

#### 残る判断（未確定事項3）

1. **分割の粒度**。週（7日）を1単位にするか、`docs/paid-leave-management-spec.md:225-242` の
   カレンダー連携を使って**園の営業日で区切る**か
2. **時間上限を超えたとき**。`shift_solve_jobs` を `failed` にせず `partial` で
   完了扱いにするか（`SolveResult.status` が持つので表現は可能）
3. **週をまたぐ制約**（最大連続勤務日数・週最大出勤日数）は分割で跨ぐため、
   **前週の結果を `fixed_assignments` として次週に渡す**必要がある

---

## 3. 未確定事項

### 3.0 確定済み

| # | 未確定事項 | 決定 | 決定日 |
| --- | --- | --- | --- |
| 1 | **施設設定の置き場** | **`shift_facility_settings` を独立させる**（3.1a の調査により決着） | 2026-10-03 |
| 2 | **1日の労働上限を gate にどう使うか** | **10時間超＝BLOCKER**（労働基準法32条違反）／**8時間45分超＝WARNING**（時間外労働・1.25倍）。8時間45分を BLOCKER にすると正職員のほぼすべての日が確定できなくなるため採らない | 2026-10-03 |
| 4 | **`planned_check_in_time` の運用** | **園児ごとの既定値＋例外日のみ上書き**。優先度は 2.9.1 の5段階 | 2026-10-03 |
| 5 | **確定の定義** | **園長が承認した時点で確定済み**とする。申請・差し戻しの段は置かない。→ 3.0e | 2026-10-03 |
| 9 | **フェーズ1の対象画面** | **画面2〜5**（施設設定／職員契約・資格の一括入力／生成／結果）。画面1・6は次段階 | 2026-10-03 |
| 11 | **時間外労働の扱い** | 現時点では**「案」**。計算上は**毎日発生しているものとして処理**する。→ 3.0f | 2026-10-03 |
| 12 | **時間外労働日数の集計元** | 打刻が毎日入っている前提で自動集計する。**翌フェーズ以降**（有給の実装と同じ scaffold を使う） | 2026-10-03 |
| 3 | **計算の単位と実行時間** | **固定7日単位で1週ずつ求解**（2.14 の実測により必須）。前週の結果を `fixed_assignments` で渡す。`PARTIAL` も正常終了で保存。→ 3.0b | 2026-10-03 |
| 6 | **職員契約の初回入力** | **CSV取り込みを先に作り**、GUI は1名ずつの編集に留める（一括編集表は対象外）。→ 3.0c | 2026-10-03 |
| 7 | **法的免責の文言** | 3か所（結果の冒頭／確定ボタン付近／出力ファイル）に置く。→ 3.0d | 2026-10-03 |
| 8 | **取り込み方式** | **`vendor/nushift/` へのコピーを採用**。submodule は未コミット38ファイルと `.dockerignore` の `.git` 除外で不適。→ 3.0a | 2026-10-03 |

**未確定は 0 項。** 3.0a〜3.0d がそのまま実装になる。

### 3.0a submodule ではなく vendor 方式にする（未確定事項8 の決定: 2026-10-03）

**submodule を実現せず、`vendor/nushift/` へのコピーを採用する。**

| 理由 | 実測 |
| --- | --- |
| nushift に**未コミット38ファイル**がある | `c5c86f3` は現在の作業状態を表現していない。submodule で固定すると**未コミットの修正がすべて除外**される |
| `.dockerignore` が `.git` を除外する | 現行 `Dockerfile` の `COPY . .` では submodule を init できない。BuildKit の `dockerfile: true` か別 clone が必要 |
| 開発と CI に手順が増える | Windows 開発・CI の双方で `git submodule update --init` が必要 |
| ビルド時にネットワークが要る | submodule / clone 方式はビルド時に GitHub への到達が必要 |

**採用方式**: `E:\nushift\nushift\src\shiftai` を `vendor/nushift/shiftai` にコピーし、
`sys.path` に `vendor/nushift` を追加する。**`pip install` はしない。**

**検証済み（2026-10-03）**: 66ファイルをコピーして `sys.path` で追加すると、
`shiftai.domain` / `standards` / `local_rules` / `solver` / `gap_analysis` が
**streamlit を入れずに** import できる。プリセット14種・`PULP_CBC_CMD` も利用可能。

**運用**: `vendor/nushift/README.md` にコピー元（`annahoikuen-debug/nushift`）と
基準コミット `c5c86f3` を残し、nushift 側が更新されたら差分を手で取り込む。

### 3.0b 計算は固定7日単位でよい（未確定事項3 の決定: 2026-10-03）

2.14 の実測で**週単位の分割が必須**と判明したので、分割の粒度を決める。

| 項目 | 決定 |
| --- | --- |
| 1回の単位 | **固定7日**（連続する7日）。園の営業日カレンダーでは区切らない |
| 営業日の扱い | 園が休む日は `shift_facility_closed_days`（2.5 の設計済み）に登録し、`closed_days` として渡す。**求解側の区分は不要** |
| 週をまたぐ制約 | 前週の結果を `fixed_assignments`（`solver.py:1382`）として次週に渡す。最大連続勤務日数・週最大出勤日数が繋がる |
| 時間上限を超えたとき | **`PARTIAL` も正常終了として保存**する。`SolveResult.ok` は PARTIAL を含む（`domain.py:1069-1071`）。画面に「完全ではない」と明示する。`failed`（解なし）のときだけエラー扱い |
| 実行の順序 | 週を順に求解する。前の週の確定結果を次の週の入力にするため、**週ごとに保存して後から再計算できるようにする** |
| 全部の週 | 一度に計算せず、**週ごとに「生成」ボタン**で進める。用户が前週を確認してから次週に進めるようにする |

> 週をまたいだ変更（前週の割り当て変更）は、`shift_plan_cells` を週ごとに
> 持つ案は実装が重い。フェーズ1では**週ごとのプランを独立に保存**し、
> 前週の `fixed_assignments` を生成時に入力する形を採る。

### 3.0c 職員契約は CSV 取り込みを先に作る（未確定事項6 の決定: 2026-10-03）

**初回入力は GUI 一括ではなく CSV 取り込みを先に用意し、GUI は1名ずつの編集に留める。**

| 理由 | 内容 |
| --- | --- |
| 入力量 | 30名 × 9項目 = **270セル**。モックでは横スクロールが常態になり、目視確認ができない |
| 既存の土台がある | `/data-transfers/`（`routers/data_transfers.py`）と `tools/family-child-csv-converter.html` の precedents があるため、形式と導線を合わせられる |
| 入力元が一致する | nushift 自体が CSV 入力（`data_loader.py:36-76`、職員は15列）。列名を合わせれば変換が楽 |
| 修正は GUI で足りる | 登録後に直すのは1名ずつなので、**行クリックで編集する**画面1枚あれば足りる |

したがって画面3 は **「CSV取り込み」（既存 `/data-transfers/` へ链接）＋「1名ずつの編集」** の
2枚に分ける。一括編集表はフェーズ1の**対象外**とする。

### 3.0d 免責の文言（未確定事項7 の決定: 2026-10-03）

`shiftai` は自治体の条例を引用するため、数値の根拠を必ず添える。**案である旨**は
3か所で繰り返す。

**1. 生成結果の冒頭バナー**

> **このシフト案は参考値です**
> 保育所の職員配置基準と労働基準法をもとに計算した**案**です。法令適合を保証するものではありません。
> 実際の勤務安排は園の責任者が判断してください。**自動保存も自動確定も行いません。**

**2. 確定ボタン付近**

> 確定すると「下書き」が「確定済み」に変わりますが、**勤務実績（打刻）には反映されません。**

**3. 出力ファイル（CSV / Excel / ICS の1行目）**

> 本書はシフト作成支援ツールが生成した参考値です。法令適合を保証するものではありません。
> 出力元: open-hoikuict 職員シフト自動作成 / 配置基準: {preset_key} / 対象: {target}

**BLOCKER があるときの追加表示**（3.0 の #2 と 3.0e の #5 に基づく）

> BLOCKER が {n} 件あるため、園長でも確定できません。配置基準・職員契約を確認してください。

### 3.0e 確定の定義（業務ルール: 2026-10-03）

**園長が承認した時点で、そのシフトは確定済みとして扱う。**

| 項目 | 内容 |
| --- | --- |
| 状態遷移 | `draft` → `generated`（生成直後）→ **`approved`（園長の承認）**。`archived` は任意 |
| 承認できる人 | **園長のみ**。`staff_role=admin`（管理者）とは別の役割として扱う |
| 実装 | `users.can_approve_shift_plans` を追加し、園長のアカウントにだけ付与する。既存の `can_manage_*` と同じフラグ方式で、`StaffPermissionChangeLog` に記録する |
| 承認の条件 | `shift_violations` と時間外労働集計に **BLOCKER が 0 件**であること。1件でもあれば承認できない（409） |
| 承認時に保存するもの | `shift_plans.status='approved'` と承認者・承認日時。`shift_solve_jobs.is_approved_snapshot` も更新する |
| 取消 | 承認後に修正する場合は `draft` に戻す（承認履歴は `shift_planning_audits` に残る） |
| 生成・編集・出力 | `users.can_manage_shifts`（園長以外でも可） |

`staff_role=admin` は `require_live_admin`（`staff_permissions.py:43-45`）で
システム管理に使われているため、**園長と同一視しない**。専用のフラグを別で持たせる。

### 3.0f 時間外労働を「毎日発生する前提」で扱う（業務ルール: 2026-10-03）

業務ルールは「時間外労働は現時点では『案』の段階であるため、計算上は毎日発生している
ものとして処理する」。以下のように実装する。

| 項目 | 実装 |
| --- | --- |
| 日単位 | **毎日**、8時間45分超を WARNING 判定する。「毎日発生する前提」なので、例外扱いにしない |
| 10時間超 | 引き続き **BLOCKER**（3.0 の #2 と不変） |
| 月5日・年6日の枠 | **BLOCKER にしない**。時間外労働が「案」の段階なので、枠は**参考表示**にとどめる |
| 「月初から既に使用した日数」の入力 | **設けない**。実データが無いため。3.0e で計画していた集計入力は撤回する |
| 年6日の累計 | 同上、**集計しない**（案の段階） |
| 画面文言 | 月次集計は「**この運用が続いた場合の想定**」と明示し、確定を止めない |

**この結果、月5日・年6日は常に超過表示になる。** 前提が「毎日発生」であるため当然で、
これは問題ではない。園が時間外労働を実際に導入した段階になったら、
枠のBLOCKER 化と集計の追加を別途に入れる。

### 3.1 未確定（ユーザー確認待ち）

**残 4 項**（#1・#2・#4・#5・#9・#10 は 2026-10-03 に確定済み）

| # | 未確定事項 | 影響 |
| --- | --- | --- |
**残 0 項。** #1〜#12 はすべて 2026-10-03 に確定し、3.0a〜3.0f に落とし込んだ。

| # | 未確定事項 | 決定先 |
| --- | --- | --- |
| （なし） | — | 3.0a vendor 方式 / 3.0b 固定7日単位 / 3.0c CSV 取り込み / 3.0d 免責文言 / 3.0e 園長承認 / 3.0f 時間外労働 |

> **#10（勤務実績との連動）だけは、3.0f の前提と重なる。** 時間外労働は「案」の段階で
> 毎日発生する前提で数えているため、実績からの集計はまだ要らない。ただし園が
> 時間外労働を実際に導入した段階で、月5日・年6日の枠を BLOCKER にするかを変하려면
> **出勤記録（打刻）からの集計が要る**。その時点までに #10 を着手する。
### 3.1a 調査で答えが出た項目

**未確定事項1（施設設定の置き場）は 2026-10-03 の調査で決着した。**

`docs/facility-settings-spec.md:158-190` の `FacilitySettings` は
*お迎え予定の最終選択時刻*・*補食判定時刻*・*補食費* の3項目で、**すべて請求・保育時間の領域**。
シフトが必要とする開園/閉園・粒度・定員・配置基準・休園日と**項目が重複しない**。
したがって `shift_facility_settings` を独立させる（= 2.5 の設計どおり）。

> ただし `docs/facility-settings-spec.md:400` の将来候補「**登園受付開始時刻**」と、
> シフトの `day_open` は概念が近い。別テーブルにすることで値が二重管理になり、
> 後から不整合が出ないよう **`day_open` は `facility-settings-spec.md` 側に持たせず
> `shift_facility_settings` が唯一の正とする**ことを明記しておく。

### 3.2 モック作成範囲（未確定事項9 の決定に基づく）

AGENTS.md と `docs/ui-prototype-workflow.md` に従い、**モックを先に**作る。
2026-10-03 の決定により **4画面**に絞る。

| # | 画面 | 種別 | 状態 |
| --- | --- | --- | --- |
| 1 | お迎え予定入力への登園予定時刻の追加、園児ごとの既定値画面 | 既存画面の変更＋新規 | **次段階**（未確定事項4 の優先度確定後に既存画面へ反映） |
| 2 | 施設設定（開園/閉園/粒度/定員/配置基準14種/休園日） | 新規 | **今回** |
| 3 | 職員契約・資格の一括入力 | 新規 | **今回** |
| 4 | 生成（対象月・配置基準の選択 → 生成中 → 完了） | 新規 | **今回** |
| 5 | 結果（配置基準表＋根拠 `basis`／シフト表／不足 `gap`／違反21種） | 新規 | **今回** |
| 6 | シフト表の手動修正とピン留め | 新規 | **次段階** |

各画面で、未入力／入力済み／一部入力／エラー（BLOCKER あり／なし／求解失敗／CBC 不在）を
切替できる確認パネルを付ける。
**本番 DB・外部送信・CBC 実行には接続しない。** 求解結果はモック用の固定値を用いる。

画面5 では、生成結果が**判断材料として読めるか**（`basis` の根拠文と不足・違反の件数）を
重点的に確認する。数値そのものの正しさはモックでは検証しない。

### 3.3 モック作成記録（2026-10-03）

作成: `tools/shift-schedule-preview/`（操作手順は同ディレクトリの `README.md`）

- URL: `http://127.0.0.1:8907/`
- サイドバーは `templates/base.html` の実マークアップを Jinja2 で描画して差し込んだ。
  基準コミット `ab947ba` とハッシュ照合（`baseline.json`）。**配備版に存在しない
  `/shifts` の項目のみ**を `基本業務` グループ・`出欠確認` の直後に追加している
- 外部読み込みゼロ（CSP で `connect-src 'none'` / `form-action 'none'`）。
  配備版は CDN の Tailwind/htmx を使うが、本モックは `style.css` で同見た目を再現した
- 架空データのみ。職員**30名**（配置対象25・配置対象外5）、定員60名の園を想定。
  種別名・職員区分・配置基準14種は `shiftai` の実列挙に合わせたが、
  **必要人数・シフト表・違反内容・人件費・労働時間はすべて仮値**であり
  `shiftai` を実行した結果ではない。シフト表と労働時間は職員ごとの契約から
  決定論的に生成する（ランダムではない）
- 自動確認: `tools/shift-schedule-preview/check.py` が 1 プロセスで
  配信 → headless Chrome → 集計までを行う。4画面 × 全状態と主要な操作を
  **40項目**実行し、2026-10-03 時点で **40項目すべて成功**（Node.js 不要）
- 未確定事項2（1日の労働上限）を画面5 に**帯域パネル**として実装した。
  上限を 10時間 / 8時間45分 / 判定しない で切り替えると、8.75〜10時間の帯域に
  いる人数と、その職員が「そのまま勤務できるか／配置し直しが必要か」を表示する。
  対象月の各日で 1〜2名が該当し、日付で変わる

**未検証**: 実データ・権限・排他・履歴・日付制約・CBC 実行・保存・通知・大量データ性能、
および画面1・画面6（次段階）。

---

## 4. 本書が扱わない事項

- **本実装・配備**。AGENTS.md のとおり、モックの試用と合意が先行する。
- **`shiftai` 側の既知の未修正事項**。`docs/09_実装計画_商業品質向上.md` §7 に
  **6件**（R2-FV-01 公平性の日次フラグが `1/n` 緩和／R2-FV-02 公平性 KPI とソルバ判定が別定義／
  R2-FV-05・R2-SOL-09 手動確定セルが契約・希望休のハード制約を迂回／
  **R2-FV-08 `daily_cap` 超過が live では WARNING・ソルバではハード制約**／
  R2-FV-16 IIS 表示の分岐が `find_conflict_core` と逆／
  R2-FV-15 `shortfall_rows` の性能）、
  および理由付きで**意図的に据え置いた2件**（R2-SOL-02 週44時間の週単位化／`is_violated` の
  fail-closed→fail-open 変更。いずれも「別途レビューが必要」と文書に残されている）。
  本提案に直接関係するのは **R2-FV-05／R2-SOL-09**（固定セルの制約迂回＝画面6）と
  **R2-FV-08**（未確定事項2）。他は `shift_schedule` の販売経路外（UI・GAS・compliance）である。
- **`nushift` の Streamlit 画面の継続**。併存は可能だが、本提案は open-hoikuict 側への集約を想定する。

---

## 5. 参考

nushift 側で先に読むべき資料:

| 資料 | 目的 |
| --- | --- |
| `docs/01_アーキテクチャ.md` | 層と依存方向の契約（`ui/` のみ Streamlit 依存） |
| `docs/02_ソルバ仕様.md` | MILP モデル、21種の違反コード表、測定値 |
| `docs/03_配置基準と自治体ルール.md` | 配置基準 14 種の根拠と出典 |
| `docs/04_データ仕様.md` | 入出力の列契約 |
| `docs/09_実装計画_商業品質向上.md` §7-§8 | 未解決バグ一覧 |

参照箇所:

- 統合先のパターン: `plan_docs/`（`contracts.py` / `db_models.py` / `store.py` / `auth_adapter.py` / `templating.py`）
- 同種の既存設計: `docs/paid-leave-management-spec.md:82`（権限列の追加）、`:225-242`（カレンダー連携）
