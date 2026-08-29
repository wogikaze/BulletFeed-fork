# ADR-0017 型付きフィードバックからのオフライン嗜好学習 v1

状態: Accepted  
版: `offline-preference-v1` / 学習入力 `preference-training-v1`  
Issue: #46 (Rec-10, extends #14, consumes #45)

## Context

`ranking-feedback-v0` は `important` / `not_relevant` の件数だけを見る。#45 の型付きシグナル（`follow`, `already_knew`, `learned_now`, `less_like_this`）を、オンラインで不透明に更新せず、再実行可能なバッチでランキングにだけ効かせる必要がある。学習は Claim / Event / Delta / Observation の正本を書き換えない（Invariant 17）。

#37 の blind Gold ラベルは学習入力に入れない。

## Options

1. オンラインでクリックごとに重みを更新する。
2. 最新フィードバックから決定論バッチで重みを再構築する（オフライン v1）。
3. フィードバックを事実訂正として ledger に戻す。

## Decision

方針 2。学習入力と政策は版付き。1 クリックでは動かない。

| パラメータ | 値 | 意味 |
| --- | --- | --- |
| `TRAINING_SCHEMA_VERSION` | `preference-training-v1` | 学習入力スキーマ。`split=blind` は拒否 |
| `POLICY_VERSION` | `offline-preference-v1` | 重み・減衰・適用政策。ランキング debug に付く |
| `MIN_EVIDENCE` | `3` | 特徴ごとの最小件数。未満は重み 0 |
| `DECAY_HALF_LIFE_SECONDS` | `30 * 24 * 60 * 60` | 指数減衰の半減期。`as_of` はバッチ内の最大 `created_at` |

### シグナル重み（正負）

| type | 重み | 役割 |
| --- | --- | --- |
| `important` | `+1.0` | 明示的な正のランキング |
| `follow` | `+0.8` | 明示的なフォロー |
| `learned_now` | `+0.35` | 有用だが弱い正 |
| `already_knew` | `+0.15` | 弱い暗黙。明示トピック/リポジトリを超えない |
| `not_relevant` | `-1.0` | 明示的な負のランキング |
| `less_like_this` | `-0.8` | 明示的な嗜好の負 |

減衰: `0.5 ** (age_seconds / DECAY_HALF_LIFE_SECONDS)`。同じフィードバック集合を同じ `as_of` で再学習すると fingerprint と重みは一致する。

疎な履歴（ユーザー全体の証拠が `MIN_EVIDENCE` 未満）は全重み 0。ベースライン順位から回帰しない。

明示トピック / 選択リポジトリに当たる item は `EXPLICIT_PROTECTED_RANK_CAP`（20）。暗黙だけの item は `IMPLICIT_RANK_CAP`（40）。preference は rank overlay のみで、importance / relation のレベルは変えない。`already_knew` のような弱い暗黙は明示選択より下に留まる。

学習状態は `user_preference_models` / `user_preference_weights` にユーザー単位で残る。検査・リセット・再学習ができる。`user_ranking_resets.reset_at` 以降だけを使う。

## Consequences

- フィード再投影は毎回バッチ再学習する。オンライン勾配はない。
- 事実 ledger は学習前後で同一。
- 政策や重みを変えるときは新しい `POLICY_VERSION` / `TRAINING_SCHEMA_VERSION` にする。

## Evidence

- `backend/app/services/offline_preference.py`
- `backend/app/services/ranking_feedback.py`
- `backend/tests/test_offline_preference.py`
- `backend/tests/test_feedback_ranking_v0.py`（非学習 v0 ベースライン）

## Rollback

`apply_feedback_ranking` から preference overlay を外し、revision 15 の表を読まなければ v0 件数政策だけに戻る。
