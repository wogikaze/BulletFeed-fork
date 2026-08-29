# ADR-0023 実世界 validation corpus の integrity 修正

状態: Accepted  
版: `real-world-validation-contract-v1.1`  
Issue: #117 (Part of)

## Context

PR #118–#121 は契約 → profile → provenance → 第1バッチの順を守った。ただし validation データ側に 4 点あった。

1. 共通 JSON を全部読んだあと `split` で filter しており、blind ラベルファイル自体を production-scoring loader が読んでいた。
2. `raw_evidence` が取得ページではなく要約で、`content_hash` は要約の改変防止にしかなっていなかった。
3. Status history / changelog index / RSS endpoint / 一般ドキュメントを event として数えていた。
4. ほぼ全 event の `occurred_at` が `2024-08-01T00:00:00Z` の仮固定値だった。

このまま F バッチと 2,000 judgment を付けると、ラベルを後から捨てることになる。

## Decision

#117 の F バッチと B3 labeling を一時停止し、integrity 修正を先に入れる。production ranking / knownness は変えない。

- record を `pilot/` `dev/` `blind/` の物理ファイルへ分離する。production-scoring は blind path を構築しない。
- schema validation → split validation → 選択の順にする。欠損 split は silent drop しない。
- 公式 API または live HTML の取得バイトを `artifacts/{source_id}/body.bin` に保存し、`content_hash` をそれに bind する。
- 個別 release / advisory / dated post だけを real event とする。index/feed/doc ページは落とす。
- 時刻は source 根拠があるときだけ入れる。なければ null。

## Consequences

第1バッチの「21 real events」は取り下げ、条件を満たす 10 件だけを残す。契約 fixture 3 件は schema 用として残すが real event ではない。50 constructed profile は残すが独立 n=50 とは扱わない。

## Rollback

評価 corpus と loader だけを戻しても feed / knownness / ranking は変わらない。
