# 実装計画書: コードレビュー指摘修正（保護者MFA・緊急通知）

- 日付: 2026-11-07
- 対象コミット: `55211d7`（fix: MFA対応、出勤レポートエクスポート権限…）
- レビュー結果: NEEDS CHANGES（WARNING 3件 / SUGGESTION 4件）

## 要望（レビュー指摘の全件修正）

| # | 指摘 | 深刻度 | 修正方針 |
|---|---|---|---|
| F1 | モバイルでMFAコードが入力できない（英字混在コード × `inputmode=numeric` × 大小文字区別） | WARNING | サーバ側 `.upper()` 統一＋テンプレート入力補助（職員側も同時対応） |
| F2 | 緊急通知の action_url が詳細に到達しない（`?notice_id=` は無視される） | WARNING | ディープリンク `/parent-portal/notices/{id}` に変更 |
| F3 | 検証されない `CredentialActionToken` が毎ログインで蓄積 | WARNING | トークン永続化を廃止し `ParentMfaPending` に一本化。旧 pending は新ログイン時的无効化 |
| F4 | `priority=high` が常に force_push（ミュート無視） | SUGGESTION | 軽量対応: 運用ルールの文書化（※本格対応は未確定事項） |
| F5 | SMTP失敗時に生500・クッキー未設定・送信予算消費 | SUGGESTION | 送信失敗を捕捉し、pending削除＋エラー画面表示 |
| F6 | credential_version 再取得比較が恒等一致（無意味） | SUGGESTION | 当該比較ブロックを削除（実保護は `resolve_parent_session` が担当） |
| F7 | MFA無効→有効切替時の既存セッション残留 | SUGGESTION | 運用手順をチェックリストに文書化 |

## こちらの解釈（確定事項）

- **スキーマ変更は行わない**（新カラム・新テーブルなし → バックアップ契約JSONの再生成は不要）。
- F1の画面変更は入力属性レベル（inputmode/autocomplete/CSS）であり、フロー・項目・遷移は不変。AGENTS.md のモック試用は、本計画書の「画面仕様」項の確認をもって代替する（ユーザー確認後に実装）。
- 職員側（`local_auth.verify_mfa_code` / `templates/staff_auth/mfa_verify.html`）もF1として同時修正する（同一バグのコピーのため）。
- F3で廃止する `issue_credential_action_token(action="mfa_verify")` 呼び出しは保護者側のみ。職員側（routers/staff_auth.py:403）は既存実装として本計画では触れない（フォローアップ）。
- コミット・配備はユーザーの指示があってから実施する。

## 修正後の画面仕様（F1 — 要確認）

- 保護者MFAコード入力欄（`/parent-portal/mfa/verify`）:
  - 入力値: 6文字の英数字（大文字小文字を**区別しない**。サーバ側で大文字化して照合）
  - モバイル: 英字キーボードが出る通常テキスト入力（`inputmode="numeric"` を廃止）
  - `autocomplete="one-time-code"`、入力内容はCSSで大文字表示（送信値はそのまま、照合はサーバ側で正規化）
  - エラー表示・試行回数・遷移は現行のまま
- 職員MFA（`/staff/mfa/verify`）も同じ入力仕様に寄せる

## 未確定事項

1. **F4の対応レベル**: (A) 運用ルール文書化のみ（本計画の既定） / (B) Noticeに「緊急配信」フラグ追加（スキーマ+UI変更→モック確認が別途必要）。既定はAで進め、Bが必要なら別計画。
2. **F3の旧pending無効化方式**: 論理失効（`expires_at` を現在時刻に更新）か削除か → 既定は**削除**（行数を増やさない）。
3. 職員側 `staff_auth.py` のトークン永続化（F3の同型問題）を本チケットに含めるか → 既定は**含めない**（フォローアップ）。

---

## 実装ステップ（1〜21）

### フェーズ0: 準備

1. **ベースライン確認** — `python -m pytest tests/auth tests/routers/test_notices.py tests/test_notification_hub.py -q` を実行し、現状の成功を記録。作業は `open-hoikuict` 直下の未コミット差分として実施。

### フェーズ1: F1 モバイル入力・大小文字（WARNING）

2. **サーバ側正規化（保護者）** — `parent_auth.py` `verify_parent_mfa_code`: `token_hash(code.strip())` → `token_hash(code.strip().upper())`（L1115付近）。
3. **サーバ側正規化（職員）** — `local_auth.py` `verify_mfa_code`: 同じく `.strip().upper()`（L778付近）。
4. **保護者テンプレート修正** — `templates/parent_auth/mfa_verify.html`: `inputmode="numeric"` を削除、`autocomplete="one-time-code"` を追加、入力を大文字表示するCSS（`text-transform:uppercase`）とモノスペース調整を追加。
5. **職員テンプレート修正** — `templates/staff_auth/mfa_verify.html`: 同じ入力補助（inputmode削除・autocomplete追加・大文字表示）。
6. **テスト追加** — `tests/auth/test_parent_login_mfa.py`: 小文字コード送信でログイン成功することを検証するテストを `_complete_mfa` 経由で追加（`code.lower()` を送るケース）。
7. **検証** — `pytest tests/auth -q` 実行、全GREEN。

### フェーズ2: F2 action_url 修正（WARNING）

8. **緊急通知のリンク修正** — `routers/notices.py` L696: `action_url=f"/parent-portal/notices/{notice.id}"` に変更。
9. **通常お知らせのリンク修正** — `notification_hub.py` L180（`notify_notice_published`）: 同じく `/parent-portal/notices/{notice_id}` 形式に変更。
10. **テスト更新** — `tests/routers/test_notices.py`（緊急テスト）と `tests/test_notification_hub.py` に `action_url` 形式のアサーションを追加。
11. **検証** — `pytest tests/routers/test_notices.py tests/test_notification_hub.py -q` 実行、全GREEN。

### フェーズ3: F3 トークン永続化の廃止（WARNING）

12. **コード生成の置換** — `routers/parent_auth.py` `parent_login`: `issue_credential_action_token(...)` 呼び出しを廃止し、`"".join(secrets.choice(ACTION_CODE_ALPHABET) for _ in range(ACTION_CODE_LENGTH))` で直接生成（`local_auth` から `ACTION_CODE_ALPHABET`, `ACTION_CODE_LENGTH` をimport）。未使用import（`issue_credential_action_token`）を削除。
13. **旧pendingの無効化** — 同関数内、新規 `ParentMfaPending` 追加前に `select(ParentMfaPending).where(parent_account_id == ...)` の既存行を `session.delete` で削除し commit（未確定事項2の既定どおり）。
14. **テスト追加** — `tests/auth/test_parent_login_mfa.py`: (a) 再ログイン後に旧pending参照が失効すること（旧クッキーでverify→400）、(b) ログイン後に `credential_action_tokens` の `mfa_verify` 行が増えないこと。
15. **検証** — `pytest tests/auth tests/routers/test_parent_enrollment.py tests/routers/test_parent_registration_links.py tests/auth/test_parent_code_mail.py -q` 実行、全GREEN。

### フェーズ4: F5 メール送信失敗時の後処理（SUGGESTION）

16. **送信失敗の捕捉** — `routers/parent_auth.py` `parent_login`: `send_auth_mail(...)` を `try/except Exception` で囲み、失敗時に (a) 作成直後の `ParentMfaPending` を削除してcommit、(b) `parent_auth/login.html` に「認証コードのメール送信に失敗しました。しばらくしてから再度お試しください。」を表示（ステータス503）。
17. **テスト追加** — `tests/auth/test_parent_login_mfa.py`: `send_auth_mail` が例外を投げる場合に503＋pending行が残らないことを検証。

### フェーズ5: F6 恒等チェックの削除（SUGGESTION）

18. **無意味な比較の削除** — `parent_auth.py` `verify_parent_mfa_code` L1125-1140: `credential.credential_version != (同一セッション再SELECT)` の比較のみを削除し、None/disabled/status の各チェックは維持。削除理由を1行コメントで記載（実保護は `AuthSession.credential_version` 検証）。

### フェーズ6: F4・F7 運用ドキュメント（SUGGESTION）

19. **緊急通知の運用ルール追記** — `docs/features.md`（通知セクション）に「`priority=重要` のお知らせは保護者のプッシュミュートを無視して緊急配信される。濫用しないこと」を明記（未確定事項1の対応A）。
20. **MFA切替の運用手順追記** — `PUBLISH_READINESS_CHECKLIST.md` に「`HOIKUICT_PARENT_LOGIN_MFA` を0→1に切替後、必要なら `revoke_parent_sessions`（parent_auth.py:1245）で保護者セッションを失効させる」旨の運用注意を追加。

### フェーズ7: 最終検証・報告

21. **全体検証と報告** — `ruff check`（変更ファイル）＋ `python -m pytest tests/ -q` フル実行（既知の環境依存失敗4種はベースラインと同一であることを確認）。変更一覧・テスト結果・未確定事項の残りを報告。**コミットはユーザー指示時のみ**。

---

## 検証マトリクス

| ステップ | 検証コマンド | 期待結果 |
|---|---|---|
| 7 | `pytest tests/auth -q` | 小文字コード成功テスト含め全GREEN |
| 11 | `pytest tests/routers/test_notices.py tests/test_notification_hub.py -q` | action_url アサーション含め全GREEN |
| 15 | `pytest tests/auth tests/routers/test_parent_*.py -q` | 旧pending失効・トークン非生成を含め全GREEN |
| 21 | `ruff check` + `pytest tests/ -q` | 既知の環境依存4失敗のみ、それ以外全GREEN |

## 影響範囲・非破壊性

- 破壊的変更なし: ログインフローのURL・遷移・クッキー名は不変。`ParentMfaPending` のスキーマ不変。
- 後方互換: 既に発行済みの旧コードは5分で失効するため、置換直後の影響なし。
- 配備: コードのみの変更でDBマイグレーション不要。`create_db_and_tables` の create_all は現状維持。
