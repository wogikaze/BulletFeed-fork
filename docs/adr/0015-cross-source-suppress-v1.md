# ADR-0015 クロスソースの繰り返し事実抑制 v1

状態: Accepted  
版: `cross-source-suppress-v1`  
Issue: #54 (Known-06)

## Context

同じ事実が複数ソースから言い直される。差分フィードでは重複カードは価値を下げるが、後続ソースの新しい証跡・詳細・訂正まで隠すと、ユーザーが知らない情報を落とす。#50 の知識同一性は同一ターゲットを束ね、#53 は hide の安全側ガードだけを定義する。繰り返し抑制はその後段で、カード畳み込みと証跡の付け替えを行う。

## Options

1. 同一 knowledge target なら後続ソースを常に hide する。
2. #53 のあとで同一事実だけを 1 枚に畳み、追加ソースは provenance として残す。不確実・DETAIL・訂正は畳まない。
3. ソースごとに常に別カードを出す。

## Decision

方針 2。パラメータは版付きで固定する。

| パラメータ | 値 | 意味 |
| --- | --- | --- |
| `POLICY_VERSION` | `cross-source-suppress-v1` | 監査用。再計算可能な版 |
| 前提ガード | `false-suppression-v1` (#53) | hide はこのガードが許可したときだけ |

判定（#53 のあと）:

- 知識同一性 (#50) が high の `same_target` で、revision が `NON_NOVEL` のときだけ畳む。
- 畳んだソースは canonical カードの `additionalSources` になる。事実は残る。
- 独立ソースは Evidence を強める。依存/配信ソースは `dependence_key` を共有し、独立証跡数を増やさない。
- `DETAIL` / `STATE_UPDATE` / `CORRECTION` / `UNRESOLVED_CONTRADICTION` / `NEW_FACT` は別カードとして出す。
- `uncertain` な同一性は畳まない、hide しない。
- #53 が hide を禁じた候補を、重複排除だけを理由に hide してはならない。

## Consequences

- 同じ未知事実の再掲は 1 枚になり、追加ソースは辿れる。
- 未知の詳細・訂正・衝突は残る。
- 繰り返し率を下げるために unknown-but-hidden を増やすことは、#53 のゲートが拒否する。

## Evidence

- `backend/app/services/cross_source_suppress.py`
- `backend/app/evaluation/cross_source_suppress.py`
- `backend/tests/gold/cross_source_suppress_v01.json`
- `backend/tests/test_cross_source_suppress.py`

## Rollback

`project_candidates` を恒等写像（全候補を displayed）に戻せば v1 以前のカード列になる。#53 のガードと #50 の同一性は残してよい。
