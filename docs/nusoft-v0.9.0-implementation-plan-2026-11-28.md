# Nusoft v0.9.0 詳細実装計画書（商業品質・現場UX・統合刷新）

- **作成日**: 2026-11-28
- **対象バージョン**:
  - `open-hoikuict`: `v0.8.2` → **`v0.9.0`**（[version.py](file:///C:/Users/user/openict/open-hoikuict/version.py)）
  - `NuShift (shiftai)`: `v0.8.1` → **`v0.9.0`**（[pyproject.toml](file:///E:/nushift/nushift/pyproject.toml)）
- **目的**: 技術的・法令的な強みを維持したまま、商業SaaSとして「ITに不慣れな園長・主任・保育士がマニュアルなしで迷わず使い続けられる」UX・情報設計・シームレス連携へ引き上げる。

---

## 1. v0.9.0 リリースゴールと定量KPI

| 指標 | v0.8.x 現状 | v0.9.0 目標 |
|---|---|---|
| 未実装・工事中ページの露出 | 1件（`/shifts/contracts`） | **0件** |
| 職員サイドバー初期表示項目数 | 30項目超のフラット表示 | **ロール別・業務フロー別折りたたみで7〜10項目** |
| 画面上の開発者用語露出 | `Zengin`, `Hard/Soft`, `JSON`, `draft` 等 | **0件（すべて現場の日本語表現へ統一）** |
| 初回シフト作成までの所要時間 | CSV準備含め数十分〜 | **在園カーブ設定により3〜5分** |
| `open-hoikuict` ⇄ `NuShift` 連携 | 手動 ZIP ダウンロード＆アップロード | **ワンクリック双方向同期（ZIP操作不要）** |
| バージョン・ドキュメント整合性 | `v0.8.1` / `v0.8.2` 混在 | **両リポジトリ `v0.9.0` 完全同期・全マニュアル更新** |

---

## 2. 全体スケジュールとフェーズ構成

```
Phase 1 (Week 1): 商用品質の止血と「現場語」統一（改善案 #1, #5）
  └─ 未実装画面解消、ハードコード撤廃、英語/開発者用語の完全日本語化

Phase 2 (Week 2): 情報設計刷新とシームレス連携（改善案 #2, #8）
  └─ ロール別ナビゲーション再編、出欠4画面のハブ化、ZIP手動往復の廃止

Phase 3 (Week 3-4): 次世代シフトUX統合と実務ワークフロー（改善案 #3, #4, #6, #7）
  └─ React月間エディタ統合、在園カーブ入力、確定後柔軟差し替え、処方箋ワンクリック仮適用

Phase 4 (Week 5): オンボーディング・業態拡大・ドキュメント総更新（改善案 #9 + Docs）
  └─ 3ステップ初期設定、小規模/企業主導型プリセット、README/MANUAL/Q&A全面改訂
```

---

## 3. 各改善案の詳細実装仕様

### Phase 1: 商用品質の止血と「現場語」統一

#### 改善案 #1: 「未実装」画面の撤去と導線・細部の商用品質化
- **対象**: `open-hoikuict`
- **対象ファイル**:
  - [templates/shift_schedule/home.html](file:///C:/Users/user/openict/open-hoikuict/templates/shift_schedule/home.html)
  - [templates/shift_schedule/contracts.html](file:///C:/Users/user/openict/open-hoikuict/templates/shift_schedule/contracts.html)
  - [templates/shift_schedule/staff_master.html](file:///C:/Users/user/openict/open-hoikuict/templates/shift_schedule/staff_master.html)
  - [templates/shift_schedule/plans_list.html](file:///C:/Users/user/openict/open-hoikuict/templates/shift_schedule/plans_list.html)
  - [shift_schedule/routers/contracts.py](file:///C:/Users/user/openict/open-hoikuict/shift_schedule/routers/contracts.py)
- **実装内容**:
  1. `/shifts/contracts`（`contracts.html` の「未実装」表示）を廃止し、実働している `/shifts/staff`（職員シフト設定・マスタ管理）へ `301` / `302` リダイレクトまたは統合する。`home.html` のリンク先も `/shifts/staff` へ統一する。
  2. `staff_master.html` L43 の `value="2026-11"` 固定値を、バックエンドから渡す `default_month`（当月または翌月 `YYYY-MM`）へ置換する。
  3. `plans_list.html` / `plan_detail.html` の `plan.status` 生表示（`draft`, `generated`, `approved`）を共通マクロで「下書き」「AI作成済み」「確定済み」の日本語バッジに変換する。
- **受け入れ基準**: 全ルートを巡回し「未実装」「TODO」「Phase X で実装予定」の文言が UI 上に 0 件であること。

#### 改善案 #5: 開発者用語（Zengin / Hardスコア / JSON / BLOCKER）の完全排除
- **対象**: `open-hoikuict` / `NuShift`
- **対象ファイル**:
  - [templates/billing/index.html](file:///C:/Users/user/openict/open-hoikuict/templates/billing/index.html)
  - [templates/shift_schedule/plan_detail.html](file:///C:/Users/user/openict/open-hoikuict/templates/shift_schedule/plan_detail.html)
  - [src/shiftai/ui/tab_solve.py](file:///E:/nushift/nushift/src/shiftai/ui/tab_solve.py)
  - [src/shiftai/ui/tab_shift.py](file:///E:/nushift/nushift/src/shiftai/ui/tab_shift.py)
- **実装内容**:
  1. `billing/index.html`: 「請求・Zengin」「Zengin作成」を「口座振替・請求管理」「銀行引落データ（全銀形式）作成」へ変更。`Billing` 等の英語見出しを廃止。
  2. `plan_detail.html`:
     - `Hard: 0` →「法令・配置基準：すべてクリア」／ `Hard > 0` →「要確認：配置・労基法アラート（N件）」。
     - `ソフト最適度スコア` →「希望・公平性マッチ度（目安）」。
     - `差分サマリ (JSON)` の生文字列出力を廃止し、`diff_review.py` 側で構造化リスト（`職員名・日付・変更前→変更後`）に整形してカード表示する。
  3. `NuShift` UI 側の `BLOCKER` / `WARNING` / `制約起訴` 表記を「必須ルール違反（確定不可）」「確認推奨」「条件の重なり内訳」などの現場語に統一する。
- **受け入れ基準**: 園長・事務員向け画面から `Zengin`, `JSON`, `Hard/Soft`, `BLOCKER` 等の技術用語が消えていること。

---

### Phase 2: 情報設計刷新とシームレス連携

#### 改善案 #2: ロール別ナビゲーション再編と「4つの出欠メニュー」統合
- **対象**: `open-hoikuict`
- **対象ファイル**:
  - [templates/base.html](file:///C:/Users/user/openict/open-hoikuict/templates/base.html)
  - [templates/portal/index.html](file:///C:/Users/user/openict/open-hoikuict/templates/portal/index.html)
  - [staff_permissions.py](file:///C:/Users/user/openict/open-hoikuict/staff_permissions.py)
- **実装内容**:
  1. `base.html` の30超のフラットなサイドバー項目を、以下の **3つの折りたたみグループ** に再編し、各職員の権限・役割に応じて関連度の低いグループをデフォルト折りたたみ（または非表示）にする：
     - **毎日の保育**: ホーム、登降園・出欠、日次連絡（連絡帳）、健康・午睡チェック、児童記録
     - **シフト・労務**: 希望休・有給申請（一般職員用）、シフト作成・管理（管理者/主任用）
     - **運営・請求・設定**: 指導計画・文書確認、口座振替・請求管理、帳票出力、園児・保護者マスタ、システム設定
  2. 重複していた「出欠一覧 (`/attendance`)」「登降園打刻 (`/toukouen`)」「出欠確認 (`/attendance-checks/`)」「子どもの名前一覧 (`/attendance-checks/roster`)」の導線を **「登降園・出欠」統合ヘッダータブ** で束ね、サイドバーには代表リンク1つのみを残す。
- **受け入れ基準**: 一般保育士ログイン時の初期サイドバー表示項目が10項目以内であること。

#### 改善案 #8: ZIP手動往復の廃止と「APIワンクリック連携」
- **対象**: `open-hoikuict` × `NuShift`
- **対象ファイル**:
  - [shift_schedule/routers/plans.py](file:///C:/Users/user/openict/open-hoikuict/shift_schedule/routers/plans.py)
  - [shift_schedule/services/solve_inputs.py](file:///C:/Users/user/openict/open-hoikuict/shift_schedule/services/solve_inputs.py)
  - [templates/shift_schedule/staff_master.html](file:///C:/Users/user/openict/open-hoikuict/templates/shift_schedule/staff_master.html)
  - [templates/shift_schedule/plans_list.html](file:///C:/Users/user/openict/open-hoikuict/templates/shift_schedule/plans_list.html)
- **実装内容**:
  1. `open-hoikuict` のシフトプラン作成・再計算時に、DB内の「園児登降園予定（または在園カーブ）」「職員資格・契約」「承認済み希望休」をメモリ上で直接 `vendor/nushift`（または分散ワーカー）へ受け渡し、結果をそのまま DB に保存するフローを主導線にする。
  2. `staff_master.html` の「NuShift連携 ZIP ダウンロード」は「外部バックアップ／詳細検証用エクスポート」としてアコーディオン内に格納し、通常運用では ZIP 操作を不要にする。
- **受け入れ基準**: ブラウザ操作のみで、希望休の承認から AI シフト生成・画面反映までファイルダウンロード／アップロードなしで完結すること。

---

### Phase 3: 次世代シフトUX統合と実務ワークフロー

#### 改善案 #3: NuShift React 月間シフトエディタ (`frontend/`) の `open-hoikuict` 統合
- **対象**: `NuShift` ([frontend/src/App.tsx](file:///E:/nushift/nushift/frontend/src/App.tsx)) × `open-hoikuict` ([templates/shift_schedule/plan_detail.html](file:///C:/Users/user/openict/open-hoikuict/templates/shift_schedule/plan_detail.html))
- **実装内容**:
  1. `NuShift` 側の React + TypeScript 月間シフトエディタ（1クリック勤務記号切替、ピン留め、Undo、`IndexedDB` 自動保存、即時法令チェック）を、サンプル14日専用から **任意月（28〜31日）・外部 JSON 初期値・保存API (`POST /shifts/plans/{id}/cells/bulk`) 連携** に対応させる。
  2. `frontend/dist` のビルド成果物を `open-hoikuict` の `static/nushift-editor/`（または `vendor/nushift` 経由）へ同梱し、`plan_detail.html` のシフトグリッド編集領域としてマウントする。
  3. コピー＆ペースト（選択セル複製）、ドラッグ連続塗りつぶし、日別不足人数バッジのリアルタイム更新を React エディタに追加する。
  4. `NuShift` 単体版のメイン導線も Streamlit から `shiftai.api` + React SPA へ段階移行し、Streamlit は「ローカル検証・旧UI互換モード」として位置づける。
- **受け入れ基準**: `plan_detail.html` 上でページリロードなしに1クリックで月間シフトの記号変更・ピン留め・元に戻す・サーバー保存ができ、配置割れが即時に赤表示されること。

#### 改善案 #4: 「園児日別CSV」不要の「クラス別・時間帯別 在園カーブ」入力ウィザード
- **対象**: `NuShift` ([src/shiftai/ui/tab_data.py](file:///E:/nushift/nushift/src/shiftai/ui/tab_data.py), [src/shiftai/demand.py](file:///E:/nushift/nushift/src/shiftai/demand.py)) & `open-hoikuict` ([shift_schedule/services/solve_inputs.py](file:///C:/Users/user/openict/open-hoikuict/shift_schedule/services/solve_inputs.py))
- **実装内容**:
  1. 「年齢別在籍数 × 標準時間帯カーブ（早朝7:00-8:30 / コア8:30-16:30 / 延長16:30-19:00 の在園割合）＋ 土曜・行事日カレンダー」から必要職員数を自動生成する簡易モデルを第1選択肢（デフォルト）として実装する。
  2. `open-hoikuict` 側では、前月の実際の登降園打刻ログから時間帯別の在園率を自動集計し、ワンクリックで翌月の需要カーブにプリセットできる機能を追加する。
- **受け入れ基準**: 園児3,000行のCSVを用意しなくても、クラス別人数と開所時間を入力するだけで月間シフト最適化が実行できること。

#### 改善案 #6: シフト「確定後」の柔軟な差し替え（版管理＋差分通知）
- **対象**: `open-hoikuict`
- **対象ファイル**:
  - [shift_schedule/db_models.py](file:///C:/Users/user/openict/open-hoikuict/shift_schedule/db_models.py)
  - [shift_schedule/routers/plans.py](file:///C:/Users/user/openict/open-hoikuict/shift_schedule/routers/plans.py)
  - [shift_schedule/routers/plans_edit.py](file:///C:/Users/user/openict/open-hoikuict/shift_schedule/routers/plans_edit.py)
  - [templates/shift_schedule/plan_detail.html](file:///C:/Users/user/openict/open-hoikuict/templates/shift_schedule/plan_detail.html)
- **実装内容**:
  1. 確定済み（`approved`）プランに対して「確定版を差し替える（改訂モード）」ボタンを新設し、確定時のスナップショット（v1）を不変履歴として保持したまま、特定日・特定職員の編集や突発欠勤リペアを実行可能にする。
  2. 差し替え確定時、変更が生じた職員（例：休み→出勤、早番→遅番）を自動抽出し、Web Push / メール / 職員ポータル通知を送るオプションを提供する。
- **受け入れ基準**: 確定済みシフトで当日病欠が発生した際、別プランを作り直すことなく1分以内に代替シフトの確定と該当職員への通知が完了すること。

#### 改善案 #7: 「処方箋」のワンクリック仮適用＆シミュレーション
- **対象**: `NuShift` ([src/shiftai/gap_analysis.py](file:///E:/nushift/nushift/src/shiftai/gap_analysis.py), [src/shiftai/ui/tab_solve.py](file:///E:/nushift/nushift/src/shiftai/ui/tab_solve.py)) & `open-hoikuict` ([templates/shift_schedule/plan_detail.html](file:///C:/Users/user/openict/open-hoikuict/templates/shift_schedule/plan_detail.html))
- **実装内容**:
  1. 処方箋生成ロジックに構造化アクションペイロード（例：`action_type: "extend_shift"`, `staff_id`, `date`, `new_end_time`, `estimated_cost_delta`）を持たせる。
  2. UI の処方箋カードに **「この案で試算する」** ボタンを配置し、押下すると Micro Engine で即座に再計算して「不足解消：○ / 人件費増減：+¥1,200」のプレビューを表示し、そのまま本適用できるようにする。
- **受け入れ基準**: 人員不足時に、提案カード上のボタン1クリックで不足解消後のシフト案をプレビュー・確定できること。

---

### Phase 4: オンボーディング・業態拡大・ドキュメント総更新

#### 改善案 #9: 「5分で自園仕様になる」初回セットアップ＆業態別プリセット
- **対象**: `open-hoikuict` & `NuShift`
- **対象ファイル**:
  - [src/shiftai/local_rules.py](file:///E:/nushift/nushift/src/shiftai/local_rules.py)
  - [src/shiftai/standards.py](file:///E:/nushift/nushift/src/shiftai/standards.py)
  - [templates/shift_schedule/facility.html](file:///C:/Users/user/openict/open-hoikuict/templates/shift_schedule/facility.html)
- **実装内容**:
  1. 初回利用時の3ステップセットアップウィザード（①開園時間・よく使う勤務記号プリセット選択 → ②園児定員・在園カーブ → ③職員名簿ひな形取込）を実装する。
  2. 配置基準プリセットに「小規模保育事業（A型・B型）」「認定こども園（教育・保育標準時間）」「カスタム配置比率（認可外・企業主導型向け目安設定）」を追加し、`NuShift` 側の適用範囲制限を緩和・明記する。
- **受け入れ基準**: 新規環境でサンプルデータではなく自園の条件（職員5〜15名）を入力して最初のシフト表が出るまで5分以内で完了すること。

---

## 4. README・マニュアル・Q&A・ドキュメント類の更新計画

v0.9.0 のリリースに合わせて、両リポジトリの全ドキュメントを同期・全面改訂する。

### 4.1 `open-hoikuict` (`C:\Users\user\openict\open-hoikuict`) の更新対象
| ファイル | 更新内容 |
|---|---|
| [version.py](file:///C:/Users/user/openict/open-hoikuict/version.py) | `__version__ = "0.9.0"` へ更新（[tests/test_version.py](file:///C:/Users/user/openict/open-hoikuict/tests/test_version.py) 確認） |
| [README.md](file:///C:/Users/user/openict/open-hoikuict/README.md) | v0.9.0 新機能（React月間シフトエディタ統合、ロール別ナビ、在園カーブ入力、確定後差し替え、ワンクリック連携）の反映 |
| [MANUAL.md](file:///C:/Users/user/openict/open-hoikuict/MANUAL.md) | スクリーンショット・画面名称の全面更新（「請求・Zengin」→「口座振替・請求管理」、新登降園ハブ、Reactシフト表の操作手順、確定後差し替え手順の追記） |
| [Q_AND_A.md](file:///C:/Users/user/openict/open-hoikuict/Q_AND_A.md) | 現場から想定される質問を追加（「確定後に職員が休んだ場合は？」「毎日の園児予定を全員分入力しないといけませんか？」「認可外・小規模園でも使えますか？」） |
| [PUBLISH_READINESS_CHECKLIST.md](file:///C:/Users/user/openict/open-hoikuict/PUBLISH_READINESS_CHECKLIST.md) | v0.9.0 セクションを追記し、未実装画面ゼロ・Reactビルド同梱・docs同期チェックを追加 |
| [docs/screen-transition-list.md](file:///C:/Users/user/openict/open-hoikuict/docs/screen-transition-list.md) | `/shifts/contracts` 廃止、出欠ハブ統合、新オンボーディング画面の遷移図更新 |
| [docs/start-manual.md](file:///C:/Users/user/openict/open-hoikuict/docs/start-manual.md) | 「5分で始める初期セットアップ」手順へ刷新 |
| [docs/specifications.md](file:///C:/Users/user/openict/open-hoikuict/docs/specifications.md) | シフト確定後改訂フロー（版管理）・在園カーブ需要算出仕様の追記 |

### 4.2 `NuShift` (`E:\nushift\nushift`) の更新対象
| ファイル | 更新内容 |
|---|---|
| [pyproject.toml](file:///E:/nushift/nushift/pyproject.toml) | `version = "0.9.0"` へ更新 |
| [README.md](file:///E:/nushift/nushift/README.md) | v0.9.0 表記統一、React SPA エディタの正式UI化、在園カーブモード・小規模/企業主導型プリセット対応の反映（「認可保育所に限定」の記述を更新） |
| [MANUAL.md](file:///E:/nushift/nushift/MANUAL.md) | React 月間シフトエディタの操作方法、処方箋ワンクリック仮適用の手順、現場語に統一した画面用語への修正 |
| [Q_AND_A.md](file:///E:/nushift/nushift/Q_AND_A.md) & [docs/FAQ.md](file:///E:/nushift/nushift/docs/FAQ.md) | Streamlit UI と React UI の位置づけ、在園カーブ入力と日別CSV入力の使い分け、不足時の処方箋機能の解説を追加 |
| [docs/01_アーキテクチャ.md](file:///E:/nushift/nushift/docs/01_アーキテクチャ.md) | `shiftai.api` + React `frontend/` + `open-hoikuict` 直接統合アーキテクチャの図解更新 |
| [docs/04_データ仕様.md](file:///E:/nushift/nushift/docs/04_データ仕様.md) | 在園カーブ設定・処方箋アクションペイロード・Reactエディタ連携APIスキーマの追記 |
| [docs/06_運用手引き.md](file:///E:/nushift/nushift/docs/06_運用手引き.md) | 確定後差し替え運用・初期セットアップ手順の追記 |

### 4.3 同期・検証作業
1. `NuShift` 側の更新完了後、`open-hoikuict` 側で `python scripts/sync_nushift_vendor.py --source E:\nushift\nushift` を実行し、`vendor/nushift/` および React ビルド成果物を同期する。
2. 両リポジトリで全テスト（`pytest` / `ruff check` / `frontend` `npm run build`）およびドキュメント整合性テスト（`test_version.py`, `test_docs_*.py`）を実行し、全件パスを確認する。

---

## 5. リリース判定チェックリスト（v0.9.0 Gate）

- [ ] `/shifts/contracts` を含む全リンクに「未実装」画面が存在しないこと
- [ ] `base.html` サイドバーの一般保育士表示が10項目以内であること
- [ ] 画面テンプレートから `Zengin`, `JSON`, `Hard/Soft`, `BLOCKER` 等の開発者用語が排除されていること
- [ ] `open-hoikuict` 画面上から ZIP 手動操作なしで AI シフト生成〜React エディタ編集〜保存〜確定ができること
- [ ] 確定済みシフトの差し替え（版管理）と変更職員への通知が動作すること
- [ ] 在園カーブ入力のみで 31 日間シフトが 15 秒以内に生成できること
- [ ] `open-hoikuict` (`v0.9.0`) と `NuShift` (`v0.9.0`) の `README.md`, `MANUAL.md`, `Q_AND_A.md`, `docs/` がすべて更新・同期されていること
- [ ] 全自動テスト（`pytest`）および Linter（`ruff`）がエラーゼロで通過すること
