# サードパーティ・オープンソースライセンス一覧 (`open-hoikuict` / Nusoft)

本ソフトウェア（`open-hoikuict` 本体は商用プロプライエタリ・All Rights Reserved）に同梱・依存している主なオープンソースソフトウェアおよびフォントのライセンス一覧です。各コンポーネントの権利はそれぞれの著作権者に帰属します。

## 1. 同梱コア・バイナリ・フォント

| コンポーネント | 用途 | ライセンス | 備考・原文 |
| :--- | :--- | :--- | :--- |
| **NuShift (`shiftai`)** | シフト自動作成 MILP エンジン | MIT License | [vendor/nushift/shiftai](vendor/nushift/shiftai)（`E:\nushift\nushift` 準拠） |
| **Caddy** | Windows 構成リバースプロキシ / TLS | Apache-2.0 | [Caddy-LICENSE.txt](assets/windows-components/Caddy-LICENSE.txt) |
| **cloudflared** | Cloudflare Tunnel クライアント | Apache-2.0 | [cloudflared-LICENSE.txt](assets/windows-components/cloudflared-LICENSE.txt) |
| **WinSW** | Windows サービスラッパー | MIT License | [WinSW-LICENSE.txt](assets/windows-components/WinSW-LICENSE.txt) |
| **Noto Sans JP** | 日本語帳票 PDF / UI フォント | SIL Open Font License 1.1 | [NotoSansJP-OFL.txt](static/fonts/NotoSansJP-OFL.txt) |
| **htmx (`htmx.min.js`)** | ローカルバンドル UI ライブラリ | BSD-0-Clause (0BSD) | [static/js/htmx.min.js](static/js/htmx.min.js) |
| **Chart.js (`chart.umd.min.js`)** | ローカルバンドル グラフ描画 | MIT License | [static/js/chart.umd.min.js](static/js/chart.umd.min.js) |

## 2. 主要 Python 依存ライブラリ (`requirements.txt`)

| パッケージ | 検証済みバージョン | ライセンス |
| :--- | :--- | :--- |
| `fastapi` | `0.135.1` | MIT |
| `starlette` | `0.52.1` | BSD-3-Clause |
| `uvicorn` | `0.41.0` | BSD-3-Clause |
| `sqlmodel` | `0.0.37` | MIT |
| `Jinja2` | `3.1.6` | BSD-3-Clause |
| `python-multipart` | `0.0.20` | Apache-2.0 |
| `httpx` | `0.28.1` | BSD-3-Clause |
| `websockets` | `16.0` | BSD-3-Clause |
| `pillow` | `12.3.0` | MIT-CMU |
| `icalendar` | `7.3.0` | BSD-2-Clause |
| `python-docx` | `1.2.0` | MIT |
| `reportlab` | `4.4.9` | BSD License |
| `xlsxwriter` | `3.2.9` | BSD-2-Clause |
| `python-dotenv` | `1.1.1` | BSD-3-Clause |
| `argon2-cffi` | `25.1.0` | MIT |
| `pywebpush` | `2.3.0` | MPL-2.0 |
| `qrcode` | `8.2` | BSD |
| `mkdocs` | `1.6.1` | BSD-2-Clause |
| `mkdocs-material` | `9.7.7` | MIT |
| `pandas` | `3.0.6` | BSD-3-Clause |
| `numpy` | `2.5.2` | BSD-3-Clause / 0BSD / MIT / Zlib / CC0-1.0 |
| `PuLP` | `2.9.0` | BSD License |
| `requests` | `2.34.2` | Apache-2.0 |

> 注意: `pywebpush` は MPL-2.0（弱いコピーレフト）ですが、ライブラリ単体を改変せずに依存利用しています。商用配布時はパッケージメタデータと本一覧を保持してください。
