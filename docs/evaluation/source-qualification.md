# Source qualification（M3）

記録済みの live HTTPS artifact は `backend/scripts/run_source_qualification.py` で
hash・evidence・duplicate replay を再検証する。外部ネットワークを使わないため、PR CI
で再現できる。

現在の live endpoint 状態を確認するときは、固定済み corpus の fetch URL から
サンプルを選び、次を実行する。

```text
python scripts/run_live_source_qualification.py --limit 200 --output tests/gold/source_qualification/v01/live_report.json
```

live runner は HTTPS、DNS 解決先、接続 peer、redirect、HTTP error、429、response size、
latency を記録する。redirect は追従せず、取得した response body は保存しない。

`source_qualification/v01/report.json` は recorded replay の証跡であり、
`live_report.json` は実行時点の live qualification の証跡である。Top-5 failure remediation
は failure dimension が観測されてから、別の regression/replay set で行う。
