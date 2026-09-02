# 実世界 validation corpus 契約（#117 Phase 0 / expansion v1.2）

版: `real-world-validation-contract-v1.2`
データセット: `real-world-validation-v0.2`  
実装: `backend/app/evaluation/real_world_validation.py`  
データ: `backend/tests/gold/real_world_validation/v01/`

後続 PR はこの契約へデータを足す。独自 schema を作らない。corpus expansion でも production algorithm は変えない。取得 artifact と label provenance を分離して保存する。

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

`record_kind=event_update` かつ `is_real_event=true` だけを real event として数える。Status history、changelog index、RSS/feed endpoint、living documentation ページ自体は event ではない。個別の release / advisory / incident / dated post だけを event にする。契約 fixture は `contract_fixture` であり real event に含めない。

## 時刻

`published_at` / `updated_at` / `observed_at` / `effective_at` / `occurred_at` を分離する。`occurred_at` は source 上の根拠があるときだけ入れる。根拠がなければ null。`2024-08-01T00:00:00Z` のような仮固定値は禁止。

## 漏洩禁止

canonical URL、同一 event、同一 update の mirror group、profile ID、redundancy group が split をまたいではならない。

## 容量目標（後続 PR）

500 real events / 120 authoritative fetch endpoints / 96 constructed profiles / 24 persona families / 10,000 AI-silver judgments / 6 source families。Japanese event は 100 件を目標とし、未達なら coverage gap として報告する。

constructed profile の variation は persona family cluster として扱い、profile 数を独立な n とみなさない。package registry / RSS artifact は `source_family` と fetch provenance を明示する。

## production scoring と不確実性

`python backend/scripts/run_m2_validation_report.py --output backend/tests/gold/real_world_validation/v01/m2_readiness_report.json`
は pilot/dev の real event だけを既存の production ranking contract で採点する。P@5/P@10、Recall@5/10、
NDCG@5/10、redundancy、important-unknown recall、unknown-but-hidden、known-but-reshown を、
cohort / persona family / language / source family / information type 別に保存する。

不確実性は constructed profile の variation を独立標本にせず、persona family cluster の deterministic
bootstrap (seed と replicate 数を report に保存) で計算する。production loader は blind path を構築せず、
AI-silver label は Human Gold として扱わない。acquisition / projection / evidence の earliest-stage
attribution は ranking 採点だけでは推定せず、別の journey trace で保存する。

## full-pipeline trace attribution

```text
python backend/scripts/run_pipeline_stage_attribution.py \
  --trace backend/tests/gold/m1_personas/v01/deterministic_baseline.json \
  --output backend/tests/gold/real_world_validation/v01/pipeline_stage_attribution.json \
  --check
```

この utility は M1/M7 の JSON trace (`reports` または単一 `stages`) を読み、各 trace の
明示された `ok=false` stage を `acquisition` → `projection` → `evidence` → `ranking` の順で
最初に観測された failure として保存する。入力の source artifact、hash、harness、repository、
trace/tenant ID、stage detail/metrics を artifact に残し、trace ごとに tenant 境界を保つ。
`feed` や `acquisition_projection` のような未分割 stage、欠落 stage、ranking の結果から
acquisition/projection/evidence を推測しない。したがって `coverage_status=partial` は
未観測を failure 0 とみなす意味ではない。

`labels_loaded=false` と `ranking_inference_used=false` は artifact 契約の必須値である。
blind path または `split=blind` trace は読む前に reject する。M2 report の
`metrics.stage_attribution` は従来どおり ranking replay 専用であり、full-pipeline の結果は
独立した `pipeline_attribution` として保存する。

## CI

通常 PR CI は契約検証、split 漏洩、artifact hash、M2 deterministic qualification を実行する。live network の追加収集は manual の collection tool で行い、取得後の corpus は通常 CI で再検証する。
