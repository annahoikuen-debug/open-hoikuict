"""models パッケージ（改善案7 / 15ステップ計画 Step 13）。

旧 `models.py`（約133KB・175クラス超）を領域別モジュールへ段階的に切り出す。
既存の `from models import X` はすべて引き続き動作する（スナップショット互換テスト:
tests/test_models_compat.py が保証する）。

現構成:
  - core:   旧 models.py の本体（切り出し途中の残り全領域）
  - notice: お知らせ（Notice*）領域
"""
from models.core import *  # noqa: F401,F403
from models.notice import (  # noqa: F401
    Notice,
    NoticeAttachment,
    NoticePriority,
    NoticeRead,
    NoticeStatus,
    NoticeTarget,
    NoticeTargetType,
    NoticeWorkflowAction,
)
from models.pims import (  # noqa: F401
    PunchChild,
    PunchLog,
)
