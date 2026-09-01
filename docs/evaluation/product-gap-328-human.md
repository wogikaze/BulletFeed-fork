# #328 人間作業（close の一部）

エージェントはこれを代替しない。今は `attestation.json` を触らない。

1. v1（`backend/tests/gold/product_gap/c1/`）は開発用。最終 blind に使わない。
2. 最終候補は `c1/v2/` の `product-gap-c1-g0-v2`。本番 SHA 固定後にだけ topic / policy / eTLD+1 をレビューする。
3. 認めたときだけ v2 の `attestation.json` を attested にする。blind を見てから直さない。
4. 正式 G6 の 7日 / 200更新は、その署名済み SHA から始める。
5. #318 / #326 / #327 の参加者集めとフォーム準備は今から並行してよい。
