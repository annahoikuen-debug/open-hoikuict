# vendor/nushift

`E:\nushift\nushift`（GitHub: `annahoikuen-debug/nushift`）のコアをコピーしたもの。

| 項目 | 値 |
| --- | --- |
| 取り込み元 | `E:\nushift\nushift\src\shiftai` |
| 基準コミット | `c5c86f3`（`master`、**38ファイルが未コミット**） |
| 取り込み日 | 2026-10-03 |
| ファイル数 | 66（`ui/` 539KB を含む） |
| 実装方針 | `docs/shift-schedule-integration-proposal-2026-10-03.md` の 3.0a |

## submodule ではなくコピーにした理由

| 理由 | 内容 |
| --- | --- |
| 未コミットがある | `c5c86f3` は現在の作業状態を表現していない。submodule で固定すると未コミットの修正 38件がすべて除外される |
| `.dockerignore` が `.git` を除外する | 現行 `Dockerfile` の `COPY . .` では submodule を init できない |
| 手順が増える | Windows 開発と CI の双方で `git submodule update --init` が必要になる |
| ビルド時にネットワーク | submodule / clone 方式はビルド時に GitHub への到達が要る |

## 使い方

`pip install` は**しない**。`sys.path` にこのディレクトリを追加する。

```python
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent / "vendor" / "nushift"))

from shiftai.domain import ChildPlan, StaffMember, Contract, Role, EmploymentType, AgeClass
from shiftai.standards import build_requirements
from shiftai.local_rules import build_standard, MUNICIPAL_PRESETS
from shiftai.solver import solve_shift
from shiftai.gap_analysis import check_violations, analyze_gap
```

## 使わないモジュール

2.2 の対象範囲どおり、`shift_schedule` から次を import しない。

| モジュール | 理由 |
| --- | --- |
| `ui/` | Streamlit。FastAPI + Jinja2/HTMX の画面が既存方針 |
| `gas_client.py` | Google Sheets 連携。既存の取り込み経路は `/data-transfers/` |
| `exporter.py` | pandas + openpyxl。既存の `XlsxWriter` / `icalendar` を使う（`openpyxl` を追加せずに済む） |
| `compliance.py` | 認可外・企業主導型向けの届出適合監査。別機能 |
| `importers.py` | CoDMON / キッズリー取込。`/data-transfers/` が既存経路 |
| `sample_data.py` / `diagnostics.py` / `live_validation.py` | 画面には不要 |

**ファイルは削除していない。** 完全なコピーなので、upstream の差分が素直に出る。
除外は **import の使い分け**で担保する。

> `gas_client.py:46` に `import streamlit as st` があるが、`try/except ImportError` の
> 内側なので streamlit 未導入でも `{}` を返して収まる。実害はない。

## 必要な依存

`requirements.txt` に次の3行のみ追加する（`streamlit` は入れない）。

```
pandas>=3.0,<4
numpy>=2.4
pulp>=2.9,<3
```

`pulp` は `<3` 厳守。PuLP 3.x/4.x は `LpVariable(..., cat=...)` と
`LpProblem(cat=LpMinimize)` の仕様を壊し、`shiftai/solver.py` の解デコードが全滅する。
CBC 実行ファイルは `pulp` ホイールに同梱されている。

## upstream を更新する手順

```powershell
Copy-Item -Recurse -Force -Path "E:\nushift\nushift\src\shiftai\*" -Destination "vendor\nushift\shiftai\"
git diff --stat -- vendor/nushift
```

更新したら `docs/shift-schedule-integration-proposal-2026-10-03.md` の
基準コミット欄と、未修正項目の記載を直す。
