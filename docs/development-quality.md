# 開発時の品質チェック

## CI

`main` へのpushとPull RequestごとにGitHub Actionsが実行される。

```text
./gradlew ktlintCheck lint
```

- `ktlintCheck`: Kotlin / Kotlin DSL のフォーマットとスタイルを検査
- `lint`: Android Lintを実行

CI設定は `.github/workflows/android-quality.yml` にある。

## ローカル

自動整形だけを行う場合:

```text
./gradlew ktlintFormat
```

検査だけを行う場合:

```text
./gradlew ktlintCheck lint
```

## コミット時の自動整形

このリポジトリには `.githooks/pre-commit` を含めている。次の一度だけ実行すると、コミット前にKotlinを自動整形し、整形チェックとAndroid Lintを実行する。

```text
git config core.hooksPath .githooks
```

hookは、すでにステージした `.kt` / `.kts` ファイルだけを再ステージする。意図しない未ステージ変更をコミット対象にしないためである。
