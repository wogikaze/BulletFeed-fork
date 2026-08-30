# Source qualification（M3）

記録済みの live HTTPS artifact は `backend/scripts/run_source_qualification.py` で
hash・evidence・duplicate replay を再検証する。外部ネットワークを使わないため、PR CI
で再現できる。

現在の live endpoint 状態を確認するときは、固定済み corpus の fetch URL から
サンプルを選び、次を実行する。

```text
python scripts/run_live_source_qualification.py --limit 200 --output tests/gold/source_qualification/v01/live_report.json
```

`live_sample_200_report.json` は200 endpointを実際に取得した保存済みsampleで、
`endpoint_count=200`、`success_rate=1.0`、`failure_dimensions={}`、median latency
3,965.293 ms を記録している。live reportはネットワーク依存のため通常PR CIでは実行せず、
このartifactとdeterministic replayを分離して扱う。

live runner は HTTPS、DNS 解決先、接続 peer、redirect、HTTP error、429、response size、
latency を記録する。redirect は追従せず、取得した response body は保存しない。

`source_qualification/v01/report.json` は recorded replay の証跡であり、
`live_report.json` は実行時点の live qualification の証跡である。Top-5 failure remediation
は failure dimension が観測されてから、別の regression/replay set で行う。
recorded reportには source family別のendpoint数、fetch成功率、duplicate failure率、
ETag/Last-Modified coverage、取得遅延の中央値、static/JS recovery countsを保存する。
記録済み3,820 replayに加え、外部通信なしの決定的transport fixtureで timeout、
conditional 304、robots disallow、redirect後のsource identity changeを各1件再生する。
一回fetchだけのcorpusでは per-source update rate を推定せず `not_recorded` と明示するが、
別snapshot pairによる update detection contract は `scenario_counts.update_detection=1` として
検証する。

## runtime verification metadata

`SourceRegistry.record_verification` は endpoint ID/URL/lineage を変更せず、
`verification_method` / `verification_reference` / `verified_at` と
`authority_method` / `authority_reference` / `authority_verified_at` を runtime 根拠として
記録する。`verified` または `authoritative` へ遷移する場合は対応する method・reference・
timestamp が必須で、未検証の静的 seed 時刻を verification evidence として扱わない。

schema migration `19` は既存 registry の identity と redirect lineage を維持したまま
metadata columns を追加する。
