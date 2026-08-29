# 実世界 validation corpus 契約（#117 Phase 0）

版: `real-world-validation-contract-v1`  
実装: `backend/app/evaluation/real_world_validation.py`  
データ: `backend/tests/gold/real_world_validation/v01/`

後続 PR はこの契約へデータを足す。独自 schema を作らない。Phase 0 では production algorithm を変えない。

## 必須 source フィールド

`source_id` / `canonical_url` / `publisher` / `source_family` / `information_type` / `language` / `collected_at` / `content_hash` / `evidence_locator` / `event_id` / `split`

## split

`pilot`（回帰） / `dev`（開発観察） / `blind`（holdout）。blind を後から都合よく動かさない。本番採点は `load_real_world_validation_for_production_scoring` のみ（pilot+dev）。

## 漏洩禁止

canonical URL、同一 event、同一 update の mirror group、profile ID、redundancy group が split をまたいではならない。

## 容量目標（後続 PR）

100 events / 50 constructed profiles / 2,000 judgments / 6 source families。契約 fixture は未達でよい。

## CI

通常 PR CI は契約検証 + 漏洩 + 小さな回帰だけ。full corpus は scheduled/manual。
