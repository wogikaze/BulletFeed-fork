# ADR-0022 実世界 Core Value 検証コーパス契約 v1

状態: Accepted（v1.1 は [ADR-0023](0023-real-world-validation-corpus-integrity.md) で改訂）  
版: `real-world-validation-contract-v1` → `v1.1`  
Issue: #117 (Part of)

## Context

#37–#75 は評価器と release gate を作ったが、現行 Gold は小さく合成的である。#117 は実世界 corpus で field-ready かを決める。巨大1PRにせず、契約を先に固定する。

## Decision

Phase 0 は schema / ID / provenance / split / leakage だけを入れる。production algorithm は変えない。容量目標（100 event / 50 profile / 2,000 judgment）は記録するが、この PR では満たさない。

split は `pilot` / `dev` / `blind`。漏洩検査は canonical URL、event、mirror group、profile ID、redundancy group。本番採点 loader は `blind/` を開かない。v1.1 ではこれを物理ファイル分離と取得 artifact への hash bind まで強化する。

後続は A を base に fan-out する（収集 / profile / ラベル / validator / evaluator）。測定された failure が出るまで ranker を直さない。

## Rollback

契約モジュールと fixture を消しても feed / knownness / ranking は変わらない。
