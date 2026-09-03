# 開発時の品質チェック

## CI

GitHub Actionsの品質チェックは、**`main` へのpush時に実行する**。Pull Requestでは実行しない。

Android（`.github/workflows/android-quality.yml`）:

```text
./gradlew ktlintCheck lint testDebugUnitTest
```

バックエンド（`.github/workflows/backend-quality.yml`、リポジトリルート）:

```text
ruff check backend
pytest backend -q --tb=short
```

各コマンドの役割は次のとおり。

- `ktlintCheck`: Kotlin / Kotlin DSLのフォーマットとスタイルを検査する
- `lint`: Android Lintを実行する
- `testDebugUnitTest`: Androidのデバッグ用ユニットテストを実行する
- `ruff check backend`: バックエンドのlintを実行する
- `pytest backend`: バックエンドのテストを実行する

`main` へのpush時には、このほかにBackend security（`pip-audit` / Bandit / Semgrep）、依存関係のlockファイル変更時のDependency lock、Backend Docker buildも実行する。

## ローカルでの確認

Kotlinの自動整形だけを行う場合:

```text
./gradlew ktlintFormat
```

CIと同じ検査を行う場合:

```text
./gradlew ktlintCheck lint testDebugUnitTest
ruff check backend
pytest backend -q --tb=short
```

`backend/` をカレントディレクトリにしている場合は、`ruff check .` と `pytest -q` でも同じ範囲を検査できる。

## コミット時の自動整形

このリポジトリには `.githooks/pre-commit` を含めている。最初に次の設定を一度だけ実行すると、コミット前にKotlinを自動整形し、整形チェックとAndroid Lintを実行できる。

```text
git config core.hooksPath .githooks
```

このhookは、すでにステージされている `.kt` / `.kts` ファイルだけを整形後に再ステージする。意図していない未ステージの変更をコミット対象へ含めないためである。
