# ADR-0014 冗長性制御付き多目的ランキング v1

状態: Accepted  
版: `multiobjective-ranker-v1`  
Issue: #44 (Rec-08)

## Context

Feed の並びは importance / relation / personalization の辞書順だった。短セッションの情報利得と冗長性を明示的に最適化できず、関連度と世界的重要度が対立するときに説明できなかった。#42 の Relation と #43 の impact は別軸として残す。不確実な knownness で hide してはならない。

## Options

1. 単一の不透明スコアに畳み込む。
2. 軸を分けた版付き政策で並べ、冗長性はペナルティだけにする。
3. 近傍重複を削除して多様性を作る。

## Decision

方針 2。政策版は `multiobjective-ranker-v1`。cursor は `v5|{policy_version}|{item_id}`。

| 軸 | 入力 | 備考 |
| --- | --- | --- |
| relevance | Relation (`direct` / `adjacent` / `reference`, score, rank) | impact に混ぜない |
| importance | `evaluate_importance` + #43 impact snapshot | Relation / novelty を見ない |
| novelty | knownness `unknown` / `probably_known` / `known` | 不確実は demote のみ。hide しない |
| redundancy | event / redundancy_group / topic occupancy | 削除せずペナルティ |
| urgency | correction / critical security / unresolved incident / deadline | 優先規則の材料 |

優先規則:

- `correction` と未解決 conflict は最優先 tier
- ユーザーに関連する critical security / critical incident は次点
- 無関係な世界的重要案件は importance 軸だけで、relevance を上書きしない

同一政策版では同じ入力から同じ順序になる。#37 evaluator（P@K / R@K / NDCG / redundancy@K）で採点する。Gold ラベルは書き換えない。

## Consequences

- 旧 v3/v4 cursor は obsolete ranking version
- 近傍重複は残るが top K を独占しない
- 軸は debug / テストで個別に観測できる

## Evidence

- `backend/app/services/multiobjective_ranker.py`
- `backend/app/stores/feed_store.py`
- `backend/tests/test_multiobjective_ranker.py`

## Rollback

`list_feed` を importance/relation/personalization の SQL 順と v4 cursor に戻せば v1 以前の契約になる。
