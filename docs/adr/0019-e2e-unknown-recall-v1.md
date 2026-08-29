# ADR-0019 ソースからフィードまでの重要未知再現率 v1

状態: Accepted  
版: `e2e-unknown-recall-v0.1`  
Issue: #72 (Eval-01)

## Context

推薦・既知度・ソースカバレッジが個別に良く見えても、重要未知情報が `/feed` まで届かないことがある。失敗箇所を段階で切り分け、unknown-but-hidden と false merge を集約点で隠してはならない。

## Decision

固定 fixture を discovery → fetch → extraction → coreference → revision → knownness → ranking の順で評価する。本番アルゴリズムは Gold を通すために変えない。blind は評価専用。

Hard gate:

- `unknown_but_hidden = 0`
- `false_merge_misses = 0`

これらは他指標で相殺できない。cold-start と history-rich は分ける。

## Rollback

評価器と fixture を外しても production feed は変わらない。
