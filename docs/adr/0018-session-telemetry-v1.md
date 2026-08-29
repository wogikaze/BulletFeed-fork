# ADR-0018 実フィードセッション成果指標 v1

状態: Accepted  
版: `session-telemetry-v1`  
Issue: #75 (Eval-04)

## Context

オフライン Gold だけでは、短セッションでユーザーが未知の有用情報に到達したかは分からない。一方で生スクロール座標や閲覧履歴の常時追跡は過剰で、feedback を世界事実に混ぜると ledger を壊す。

## Options

1. スクロール座標とカード滞在を高頻度で保存し、後から成果を推定する。
2. 明示イベントだけを別スキーマに残し、オフにしても feed が動くようにする。
3. Gold だけに頼り、実セッション指標を持たない。

## Decision

方針 2。revision 16 で `feed_sessions` / `feed_session_outcomes` を追加する。

- kind: `session_start` / `card_displayed` / `detail_read` / `feedback` / `follow` / `session_end`
- 生スクロール座標は保存しない。意味露出は既存 exposures 判定の後に 1 行だけ書く。
- GET `/feed` では session を開始しない。
- 欠損・無効化は no-op。Event / Claim / Delta / Observation は書き換えない。
- 保持は 30 日。ユーザーは `DELETE /me/feed-sessions` で消せる。
- `BULLETFEED_SESSION_TELEMETRY_ENABLED=false` で無効化できる。

## Consequences

useful-card rate / already-known re-show / cards-to-useful / feedback response をセッションから推定できる。#72/#73 の実測入力になる。

## Rollback

設定を切るか revision 16 表を読まなければ feed は従来どおり動く。
