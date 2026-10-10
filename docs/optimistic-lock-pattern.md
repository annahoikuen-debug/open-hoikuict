# 楽観的ロックパターン

> 作成日: 2026-10-10 / 対象モジュール: `common/optimistic_lock.py`

---

## 概要

複数の職員が同時に同じレコードを編集した場合の上書き衝突を防ぐためのパターン。  
「読み取り時の版番号（`lock_version`）が更新時にも一致するか」を DB レベルで確認し、
不一致なら `ConcurrentUpdateError` を送出してロールバックする。

---

## 共通モジュール

```
common/optimistic_lock.py
```

| 関数・クラス | 用途 |
|---|---|
| `ConcurrentUpdateError` | バージョン不一致時の例外（ロールバック済み） |
| `claim_lock()` | TEXT UPDATE ベース（notices 系） |
| `claim_lock_orm()` | SQLAlchemy ORM `update()` ベース（plan_docs 系） |

---

## `claim_lock` — TEXT UPDATE パターン

notices など、単純なテーブル向け。

```python
from common.optimistic_lock import claim_lock, ConcurrentUpdateError

# エンドポイント例
@router.post("/{notice_id}/approve")
def approve_notice(notice_id, lock_version: int = Form(...), ...):
    ...
    try:
        claim_lock(
            session,
            table_name="notices",
            id_col="id",
            id_val=notice_id,
            expected_version=lock_version,
        )
    except ConcurrentUpdateError:
        raise HTTPException(status_code=409, detail=str(exc))
    notice.status = NoticeStatus.published
    session.add(notice)
    session.commit()
```

### SQL 生成例

```sql
UPDATE notices
SET lock_version = lock_version + 1,
    updated_at   = :updated_at
WHERE id = :id_val
  AND lock_version = :expected_version;
```

`rowcount != 1` の場合：`session.rollback()` + `ConcurrentUpdateError` を送出。

---

## `claim_lock_orm` — ORM UPDATE パターン

`plan_docs` の `PlanDocumentHeadRow` など、ORM モデルが使えるケース向け。

```python
from common.optimistic_lock import claim_lock_orm

# plan_docs/store.py での呼び出し（SqlModelDocumentRepository._claim_lock より）
claim_lock_orm(
    self.session,
    model_class=PlanDocumentHeadRow,
    where_col="document_id",
    id_val=document_id,
    expected_version=expected_lock_version,
)
```

---

## テンプレート側の実装

フォームに `lock_version` を hidden フィールドで埋め込む：

```html
<input type="hidden" name="lock_version" value="{{ notice.lock_version }}">
```

---

## エラーハンドリング

### ルーター側

```python
from common.optimistic_lock import ConcurrentUpdateError

try:
    claim_lock(session, ...)
except ConcurrentUpdateError as exc:
    raise HTTPException(status_code=409, detail=str(exc))
```

### フロント側

- 409 受信時：「他の職員が先に更新しました。画面を再読み込みしてください。」を表示
- ページリロード → 最新の `lock_version` を取得 → 再試行

---

## 実装済みドメイン

| ドメイン | テーブル / モデル | 関数 | 対象操作 |
|---|---|---|---|
| notices | `notices` | `claim_lock` | 承認・差戻し・`unpublish` |
| plan_docs | `plan_document_heads` | `claim_lock_orm` | 編集・ステータス変更 |

---

## 将来の適用候補

| ドメイン | 検討内容 |
|---|---|
| `child_records` | 観察訂正の `expected_updated_at` チェックを `lock_version` ベースに移行（既存 `updated_at` 互換維持が必要） |
| `shift_schedule` | 承認フロー実装時に `shift_plans` へ適用 |

---

## 不変条件

- `table_name` と `id_col` は **リテラル文字列** を渡すこと（SQL インジェクション対策）
- `rowcount != 1` になった場合は必ず `session.rollback()` を呼んでから例外を送出する（共通関数内で実施済み）
- 例外メッセージは日本語で統一：「他の職員が先に更新しました。画面を再読み込みしてください。」
