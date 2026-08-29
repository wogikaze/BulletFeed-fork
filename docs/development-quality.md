# 開発時の品質チェック

## CI

GitHub Actions の quality workflow は **`main` への push だけ** 実行する（Pull Request では走らない）。

Android（`.github/workflows/android-quality.yml`）:

```text
./gradlew ktlintCheck lint testDebugUnitTest
```

Backend（`.github/workflows/backend-quality.yml`、リポジトリルート）:

```text
ruff check backend
pytest backend -q --tb=short
```

- `ktlintCheck`: Kotlin / Kotlin DSL のフォーマットとスタイルを検査
- `lint`: Android Lint
- `testDebugUnitTest`: Android debug unit tests
- `ruff check backend`: Backend lint
- `pytest backend`: Backend tests

`main` への push ではこのほか Backend security（`pip-audit` / Bandit / Semgrep）と、backend lock 変更時の Dependency lock、Backend Docker build も走る。

## ローカル

自動整形だけを行う場合:

```text
./gradlew ktlintFormat
```

CI と同じ検査:

```text
./gradlew ktlintCheck lint testDebugUnitTest
ruff check backend
pytest backend -q --tb=short
```

`backend/` をカレントにする場合は `ruff check .` と `pytest -q` でも同じ対象になる。

## コミット時の自動整形

このリポジトリには `.githooks/pre-commit` を含めている。次の一度だけ実行すると、コミット前にKotlinを自動整形し、整形チェックとAndroid Lintを実行する。

```text
git config core.hooksPath .githooks
```

hookは、すでにステージした `.kt` / `.kts` ファイルだけを再ステージする。意図しない未ステージ変更をコミット対象にしないためである。
