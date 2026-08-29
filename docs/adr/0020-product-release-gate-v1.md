# ADR-0020 非対称プロダクト価値リリースゲート v1

状態: Accepted  
版: `product-release-floors-v1`  
Issue: #73 (Eval-02)

## Context

個別ベンチが良くても、unknown-but-hidden や false merge が悪化したまま集約点が上がることがある。下限は版と理由を持ち、静かに変えてはならない。

## Decision

`tests/gold/product_release/v01/floors.json` を唯一の下限にする。hard gate は unknown-but-hidden と false merge。重複再表示や false split より厳しい。cold-start / history-rich は別下限。変更は version と reason を更新する。

## Rollback

ゲートを外しても production アルゴリズムは変わらない。
