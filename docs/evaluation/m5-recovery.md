# M5 Recovery Qualification

M5は、SQLite/スナップショットの破損境界を含む in-process regression と、API/worker
process boundary の再起動 drill を分けて検証する。

## 自動で再実行できる検証

```text
cd backend
python scripts/run_recovery_security_suite.py
python scripts/run_process_recovery_drill.py --output tests/gold/recovery/v01/process_recovery_report.json
```

`test_web_snapshots.py` は atomic publish、metadata/body の partial-write cleanup、
immutable identity、retention/容量 GC、参照snapshot保護を fault injection で検証する。
`run_process_recovery_drill.py` は一時DBでAPIとworkerを別processとして起動し、worker停止・再起動、
API停止・再起動後のsession persistenceを確認する。

## Docker host/process drill

Docker daemon が利用できる環境では、独立したCompose projectとvolumeを使う次のdrillを実行する。

```text
cd backend
python scripts/run_host_recovery_drill.py --output tests/gold/recovery/v01/host_recovery_report.json
```

このscriptは一時env/compose定義を生成し、fresh stackのreadiness、session作成、bounded tmpfs
上のsnapshot ENOSPC cleanup、API restart、worker restart、restart後のsession lookupを検証して
から、自分のprojectだけを削除する。生成env、token、database path、project名はreportへ出力しない。
通常PR CIはDocker daemonやhost filesystem quotaに依存しないため、このhost drillを自動実行しない。

Docker daemonが無い場合はcommand自体を失敗として記録し、passへ置き換えない。bounded tmpfsの
ENOSPCは自動検証するが、永続volumeの実disk-fullはhost-specific fault injectionが必要であり、
独立した残課題として扱う。

GitHub ActionsのDocker runnerで取得した成功結果は
`backend/tests/gold/recovery/v01/host_recovery_report.json` に保存する。reportには実行した
repository SHAとworkflow run IDを含め、restart後のAPI/worker readinessとsession persistenceを
再現可能な証跡として結び付ける。
