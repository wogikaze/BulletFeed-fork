# Clean-room acceptance（M7）

Backend の clean-room journey は、既存の開発用 DB/cache/secret を使わず、
一時ディレクトリに API・worker・SQLite を作って次を実行する。

```text
cd backend
python scripts/run_clean_room_backend_acceptance.py
```

証跡を保存する場合は `--output tests/gold/clean_room/v01/backend_report.json` を付ける。
report は token を保存せず、user ID と各 stage の pass/fail だけを記録する。

検証する順序は fresh stack/readiness、session、profile/topic onboarding、source
discovery、activation、subscription、acceptance acquisition/projection、feed、
Event evidence、meaningful exposure、feedback、subsequent feed である。worker/API
process recovery と Android release build は M5/M4 の専用 gate で別途実行する。

この backend harness の source acquisition は deterministic acceptance fixture を
使う。live OAuth、実ユーザー登録、公開 HTTPS backend 上の field validation は
意図的に含めず、最終 RC 判定では別の blocker として扱う。
