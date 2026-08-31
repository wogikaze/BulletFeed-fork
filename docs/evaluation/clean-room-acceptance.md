# Clean-room acceptance（M7）

Backend の clean-room journey は、既存の開発用 DB/cache/secret を使わず、
一時ディレクトリに API・worker・SQLite を作って次を実行する。

```text
cd backend
python scripts/run_clean_room_backend_acceptance.py
```

証跡を保存する場合は `--output tests/gold/clean_room/v01/backend_report.json` を付ける。
report は token と ephemeral user ID を保存せず、各 stage の pass/fail だけを記録する。

検証する順序は representative schema upgrade、fresh stack/readiness、session、profile/topic onboarding、source
discovery、activation、subscription、acceptance acquisition/projection、feed、
Event evidence、meaningful exposure、feedback、subsequent feed である。worker/API
process recovery と Android release build は M5/M4 の専用 gate で別途実行する。
schema upgrade stage は別の一時DBで旧migration markerを再適用し、既存user stateが保持され、
current `KNOWN_REVISIONS` へ到達することを確認する。

Android の real-backend acceptance は `com.bulletfeed.app.RealBackendAcceptanceTest` を
fresh ephemeral backendへ接続して実行する。結果は
`backend/tests/gold/android_acceptance/v01/acceptance_report.json` に集約し、release APKは
対応する Android Actions artifact として保存する。APK binaryやbackend tokenはcommitしない。

この backend harness の source acquisition は deterministic acceptance fixture を
使う。live OAuth、実ユーザー登録、公開 HTTPS backend 上の field validation は
意図的に含めず、最終 RC 判定では別の blocker として扱う。1週間の field 手順と
人間ブロッカーは `docs/evaluation/field-eval-protocol.md` と
`docs/operations/field-eval-human-blockers.md` を正とする。current SHA の RC
bundle 再生成は `docs/operations/rc-evidence.md`。field を回しても
`completion_gate_pass` は自動では true にならない。
