# 実世界 validation corpus 契約（#117 Phase 0 / integrity v1.1）

版: `real-world-validation-contract-v1.1`  
データセット: `real-world-validation-v0.2`  
実装: `backend/app/evaluation/real_world_validation.py`  
データ: `backend/tests/gold/real_world_validation/v01/`

後続 PR はこの契約へデータを足す。独自 schema を作らない。Phase 0 では production algorithm を変えない。F1–F5 収集と B3 labeling は、この integrity 契約が main に入るまで再開しない。

## 必須 source フィールド

`source_id` / `canonical_url` / `publisher` / `source_family` / `information_type` / `language` / `collected_at` / `content_hash` / `evidence_locator` / `event_id` / `split` / `source_role` / `fetch` / `evidence_text` / `normalized_evidence`

`content_hash` は手書き要約ではなく、`artifacts/{source_id}/body.bin` の取得バイトに bind する。`evidence_text` はその artifact 内の exact substring でなければならない。

## 物理 split

```text
{split}/sources.json
{split}/events.json
{split}/profiles.json
{split}/judgments.json
{split}/index.json
```

`pilot`（回帰） / `dev`（開発観察） / `blind`（holdout）。本番採点は `load_real_world_validation_for_production_scoring` のみ。この loader は `pilot`/`dev` の path だけを構築し、blind ラベルファイルを open/read しない。

各 split ファイルは、filter の前に全 record を schema validation する。`split` 欠損や不正値は silent drop せずエラーにする。record の `split` はディレクトリ名と一致しなければならない。

## real event

`record_kind=event_update` かつ `is_real_event=true` だけを real event として数える。Status history、changelog index、RSS/feed endpoint、living documentation ページ自体は event ではない。個別の release / advisory / incident / dated post だけを event にする。契約 fixture は `contract_fixture` であり real event に含めない。件数が 21 未満でよい。

## 時刻

`published_at` / `updated_at` / `observed_at` / `effective_at` / `occurred_at` を分離する。`occurred_at` は source 上の根拠があるときだけ入れる。根拠がなければ null。`2024-08-01T00:00:00Z` のような仮固定値は禁止。

## 漏洩禁止

canonical URL、同一 event、同一 update の mirror group、profile ID、redundancy group が split をまたいではならない。

## 容量目標（後続 PR）

100 real events / 50 constructed profiles / 2,000 judgments / 6 source families。いまは未達でよい。

50 constructed profile は初期 fixture としては残す。ただし persona template は 8 家族に偏っている。将来「n=50」とは扱わず、bootstrap は persona family の cluster を検討する。

## CI

通常 PR CI は契約検証 + 漏洩 + 小さな回帰だけ。full corpus は scheduled/manual。
