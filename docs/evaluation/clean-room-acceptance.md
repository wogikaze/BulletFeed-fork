# Clean-room acceptance（M7）

Backend の clean-room journey は、既存の開発用 DB/cache/secret を使わず、
一時ディレクトリに API・worker・SQLite を作って次を実行する。

```text
cd backend
python scripts/run_clean_room_backend_acceptance.py
```

証跡を保存する場合は `--output tests/gold/clean_room/v01/backend_report.json` を付ける。
report は token と ephemeral user ID を保存せず、各 stage の pass/fail だけを記録する。

Android の同じ clean-room API/worker process に既存の
`com.bulletfeed.app.RealBackendAcceptanceTest` を接続し、release APK も組み立てる
CI 経路は次で実行する。

```text
python backend/scripts/run_clean_room_backend_acceptance.py \
  --android-release-client \
  --run-android-lifecycle \
  --output "$RUNNER_TEMP/m7-clean-room-android.json"
```

この経路は backend stage 完了後も同じ ephemeral backend を停止せずに JVM
real-backend acceptance を実行するため、別の acceptance を複製しない。release APK は
`https://clean-room.invalid/` という synthetic HTTPS URL で package 検証のためだけに
assemble し、公開 backend への接続や field validation は行わない。既定の
`app-release-unsigned.apk` は package artifact であり、署名済み field APK として扱わない。

report には `lifecycle.install`、`lifecycle.upgrade`、`lifecycle.recovery` を必ず含める。
通常 CI は ADB の実行を試みるが、ready な emulator/device が無ければ各 status は
`not_available` となり、全体 status は `partial`、`completion_gate_pass` は `false` の
ままである。デフォルトでは端末データを変更せず、install/uninstall を実行しない。
破壊的な clean install を行う場合は `--allow-adb-data-wipe` を明示し、runner は
`ro.kernel.qemu=1` の disposable emulator 以外を拒否する。ADB の timeout、起動後の
OS error、unexpected non-zero は `failed` として bounded な理由を保存する。upgrade は
previous/current APK の同一 package・異なる versionCode とデータ保持を検証できない限り
`not_available` であり、package replacement を upgrade として記録しない。これは package/process 操作の証跡で
あり、Android UI、OAuth、session/credential recovery、device breadth、field evidence
を代替しない。必須化する場合だけ `--require-android-lifecycle` を追加し、未実行・未提供
なら exit 1 にする。

検証する順序は representative schema upgrade、fresh stack/readiness、session、profile/topic onboarding、source
discovery、activation、subscription、acceptance acquisition、projection、feed、
Event evidence、meaningful exposure、feedback、subsequent feed である。acquisition と projection は
seed response の event ID と projected item count を別々に検証する。worker/API
process recovery は M5 の専用 gate で別途実行する。Android release build は上記の
integrated mode で package artifact を作るが、公開 backend への接続は行わない。
schema upgrade stage は別の一時DBで旧migration markerを再適用し、既存user stateが保持され、
current `KNOWN_REVISIONS` へ到達することを確認する。
この report は `trace_id=m7-clean-room` の単一 ephemeral tenant trace であり、
次のコマンドで provenance を保ったまま stage attribution を再生成できる。

```text
python backend/scripts/run_pipeline_stage_attribution.py \
  --trace backend/tests/gold/clean_room/v01/backend_report.json
```

Android の standalone real-backend acceptance は
`com.bulletfeed.app.RealBackendAcceptanceTest` を fresh ephemeral backendへ接続して
実行する。結果は `backend/tests/gold/android_acceptance/v01/acceptance_report.json` に
集約し、release APKは対応する Android Actions artifact として保存する。統合 CI report
は runner artifact として保存し、APK binaryやbackend tokenは commit しない。既存の
backend-only report と Android/field evidence は同一視しない。

この backend harness の source acquisition は deterministic acceptance fixture を
使う。live OAuth、実ユーザー登録、公開 HTTPS backend 上の field validation は
意図的に含めず、最終 RC 判定では別の blocker として扱う。1週間の field 手順と
人間ブロッカーは `docs/evaluation/field-eval-protocol.md` と
`docs/operations/field-eval-human-blockers.md` を正とする。current SHA の RC
bundle 再生成は `docs/operations/rc-evidence.md`。field を回しても
`completion_gate_pass` は自動では true にならない。
