# ADR-0013 不確かな既知度に対する保守的な誤抑制ガード v1

状態: Accepted  
版: `false-suppression-v1`  
Issue: #53 (Known-05)

## Context

既知情報の繰り返しを減らすことと、ユーザーが知らない重要事実を隠さないことは非対称である。誤って hide する方が、重複を再表示するより損害が大きい。#49 の証跡既知度と #50 の意味同一性はそれぞれ `may_hide` を持つが、訂正・衝突・古い露出・曖昧な言い換えを合成して判定する場所がなかった。

#54 のクロスソース繰り返し抑制はこの ADR の対象外。このガードは hide を許可する前提条件だけを定義する。

## Options

1. 既知度が `known` / `probably_known` なら hide する（繰り返し最小化）。
2. 高信頼の `known` かつ意味同一が確定しているときだけ hide し、不確実なら show / demote に落とす。
3. hide を廃止し、常に demote する。

## Decision

方針 2。パラメータは版付きで固定する。

| パラメータ | 値 | 意味 |
| --- | --- | --- |
| `POLICY_VERSION` | `false-suppression-v1` | 監査用。再計算可能な版 |
| `MIN_HIDE_CONFIDENCE` | `high` | hide に必要な既知度・同一性の下限 |

判定（先に安全側）:

- `uncertain` な既知度・同一性・同等性は **hide 禁止**。show または demote のみ。
- 低信頼の既知度は、critical / high の未知情報を抑制できない。
- `CORRECTION` / `UNRESOLVED_CONTRADICTION` は通常の既知度 hide を越えて surface する。
- 古い露出（stale exposure）は不確実な既知度として扱う。
- 部分詳細や異なる knowledge target は重複として hide しない。
- hide した候補は必ず `reason` と `version` を残す。同じ入力で再実行すれば理由を再構成できる。

評価:

- `false_suppression_rate`（unknown-but-hidden）と `repetition_rate` は独立指標。
- 繰り返し率を下げるために unknown-but-hidden を実質的に増やす回帰はリリースゲートで拒否する。

## Consequences

- 曖昧な言い換えは再表示または demote され、hard-hide されない。
- 自信のある既知の言い換えだけが hide できる。
- #54 が繰り返し抑制を足すときも、このガードを通さない hide は禁止。

## Evidence

- `backend/app/services/false_suppression.py`
- `backend/app/evaluation/false_suppression.py`
- `backend/tests/gold/false_suppression_v01.json`
- `backend/tests/test_false_suppression.py`

## Rollback

`decide_suppression` を常に `presentation_for_item`（#49）へ委譲すれば v1 以前の証跡のみの判定に戻る。評価ゲートは残してよい。
