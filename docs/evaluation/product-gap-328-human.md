# #328 人間作業（close の一部）

エージェントはこれを代替しない。今は `attestation.json` を触らない。

1. v1（`backend/tests/gold/product_gap/c1/`）は開発用。最終 blind に使わない。
2. 最終候補は `c1/v2/` の `product-gap-c1-g0-v2`。本番 SHA 固定後にだけ topic / policy / eTLD+1 をレビューする。
3. 認めたときだけ v2 の `attestation.json` を attested にする。blind を見てから直さない。
4. 正式 G6 の 7日 / 200更新は、その署名済み SHA から始める。
5. #318 / #326 / #327 の参加者集めとフォーム準備は今から並行してよい。

## 現在の dev evidence（Human Gold ではない）

`c1/v2/` は 341 source（eligible 333）、24 topics、JA 115、no-RSS 73、
blind 31.38%、policy_blocked 8。`sources.json` は freeze の SHA-256 と照合する。
`attestation.json` は `awaiting_operator_attestation` のまま。

- G1 production confirm: 234 source、feed recall 0.5818、confirm 後 P@3 0.6892、
  JA 0.5833、no-feed fallback 0.3372。`g1_measurement.json`。
- G2 topic-only discovery: primary R@20 0.4024、relevant R@50 0.3260、
  P@20 0.3645、JA 0.1412、blog 0.3000、no-RSS 0.4571。
  `gold_injected=false`。`g2_measurement.json` と baseline を併記する。
- G3 同一 feed URL の独立 oracle parity: 55 attempted / 37 successful / 18 failed、
  raw recall 0.6727、important recall 0.6727。family regression は未測。
- G4 production preview → article enrichment: 100 items、body success 0.5455、
  important body recall 0.75。update recall/precision と article split は未測。
- G5: URL shape 106 cases の bypass 0。controlled production path は 4/4、
  real live network は未測。

再実行:

```text
python backend/scripts/run_product_gap_c1.py
python backend/scripts/audit_product_gap_c1_hard_gate.py --output <audit.json>
```

未測・sample incomplete・floor 未達・operator attestation pending はすべて
Completion Gate の FAIL として扱う。これらの dev 数値だけで #328 を close したり、
Human Gold と呼んだりしない。
