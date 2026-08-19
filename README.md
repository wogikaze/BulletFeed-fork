# BulletFeed

追っている技術・サービス・企業に起きた重要な変化を、**自分との関係**と**重要度**がひと目で分かる形で届けるAndroidアプリのプロトタイプです。

記事を並べるのではなく、複数の情報源を統合した「イベント」を読むことを目指します。

## 現在の実装

- Jetpack ComposeによるAndroid UI
- 重要度（緊急 / 重要 / 注目 / 参考）と関連性（直接影響 / 近接影響 / 参考情報）の表示
- イベント詳細: 変更前後、影響、時系列、根拠ソース
- フィードバック: 重要、不要、フォロー
- イベント検索
- テーマ管理とGitHub連携フローのデモUI
- バックエンド不要のデモデータ

GitHub連携は現在UIデモです。本番ではアプリがGitHub認可画面を開き、バックエンドが認可コード交換とトークン保管を担います。

## 起動方法

Android Studioでプロジェクトルートを開き、エミュレータまたは実機を選んで `app` を実行してください。

必要環境:

- Android Studio
- JDK 17（Android Studio内蔵のJBRで可）
- Android SDK Platform 36

コマンドラインでデバッグAPKを作る場合:

```bash
./gradlew :app:assembleDebug
```

APKは `app/build/outputs/apk/debug/app-debug.apk` に生成されます。

## 品質チェック

Kotlinの整形にはktlint、Android固有の静的解析にはAndroid Lintを使用します。

```bash
# Kotlin / Kotlin DSLを自動整形
./gradlew ktlintFormat

# Kotlinの書式チェックとAndroid Lint
./gradlew ktlintCheck lint
```

`main` へのpushとPull Requestでは、GitHub Actionsが同じチェックを実行します。設定は [.github/workflows/android-quality.yml](.github/workflows/android-quality.yml) にあります。

### コミット時の自動整形

リポジトリにはpre-commit hookが含まれています。次のコマンドを一度実行すると、コミット時にKotlinを自動整形し、書式チェックとAndroid Lintを実行します。

```bash
git config core.hooksPath .githooks
```

hookは、すでにステージした `.kt` / `.kts` ファイルだけを再ステージします。

## ドキュメント

- [フロントエンドMVP仕様](docs/frontend-mvp-spec.md)
- [API契約 v1](docs/api-contract-v1.md)
- [データソース方針](docs/data-sources-mvp.md)
- [品質チェック詳細](docs/development-quality.md)

## プロジェクト構成

```text
app/src/main/java/com/bulletfeed/app/
  data/          # デモデータ（将来はAPI実装）
  domain/        # Eventなどのドメインモデル
  ui/
    components/  # 共通Compose部品
    feed/        # フィード
    search/      # 検索
    detail/      # イベント詳細
    management/  # テーマ・GitHub連携・設定
```
