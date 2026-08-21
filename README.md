# BulletFeed

追っている技術・サービス・企業に起きた重要な変化を、**自分との関係**と**重要度**がひと目で分かる形で届けるAndroidアプリのプロトタイプです。

記事を並べるのではなく、複数の情報源を統合した「イベント」を読むことを目指します。

## 現在の実装

- Jetpack ComposeによるAndroid UI
- 重要度（緊急 / 重要 / 注目 / 参考）と関連性（直接影響 / 近接影響 / 参考情報）の表示
- イベント詳細: 変更前後、影響、時系列、根拠ソース
- フィードバック: 重要、不要、フォロー
- イベント検索
- GitHub依存関係に影響する脆弱性の一覧・詳細・対応状況管理（デモデータ）
- 重要な変化をまとめる通知センター、未読バッジ、すべて既読
- テーマ管理とGitHub連携フローのデモUI
- `ViewModel + StateFlow + Repository` による状態管理
- FastAPI実装へ差し替え可能なMock Repository
- 読み込み中・取得失敗・再試行の状態表示
- プロフィール、5件以上の追跡テーマ、GitHub連携を設定する3ステップオンボーディング
- オンボーディング結果をテーマ・設定画面へ反映

GitHub連携は現在UIデモです。本番ではアプリがGitHub認可画面を開き、バックエンドが認可コード交換とトークン保管を担います。

## 任意利用のバックエンド

`backend/` にFastAPIの参考実装を同梱しています。Androidフロントエンドの起動には不要ですが、GitHub認証、公開リリース、OSV、許可済みRSS、Statuspageの取得を試す場合に利用できます。

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

詳細は [バックエンドREADME](backend/README.md) と [データ取得・法務ガードレール](backend/LEGAL_AND_SOURCE_POLICY.md) を参照してください。これはローカル検証用プロトタイプであり、フロントエンドは引き続きMock Repositoryだけでも動作します。

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

# Mock Repositoryの状態更新テスト
./gradlew :app:testDebugUnitTest
```

`main` へのpushとPull Requestでは、GitHub Actionsが同じチェックを実行します。設定は [.github/workflows/android-quality.yml](.github/workflows/android-quality.yml) にあります。

`backend/` に変更があるPull Requestでは、[backend-quality.yml](.github/workflows/backend-quality.yml) がRuffとpytestを実行します。

### コミット時の自動整形

リポジトリにはpre-commit hookが含まれています。次のコマンドを一度実行すると、コミット時にKotlinを自動整形し、書式チェックとAndroid Lintを実行します。

```bash
git config core.hooksPath .githooks
```

hookは、すでにステージした `.kt` / `.kts` ファイルだけを再ステージします。

## GitHub運用ルール

`main` は保護ブランチです。直接pushはできないため、すべての変更は作業ブランチからPull Requestを作成します。

マージには次の条件が必要です。

- GitHub Actionsの `Lint and format check` が成功している
- 1人以上のレビュアーが承認している
- PR内の会話がすべて解決されている
- PRブランチが最新の `main` に追従している

force pushと`main`ブランチの削除も禁止しています。

## ドキュメント

| ドキュメント | 内容 |
| --- | --- |
| [フロントエンドMVP仕様](docs/frontend-mvp-spec.md) | 画面構成、ユーザー導線、Compose実装の責務、デモからAPI接続へ移るための方針 |
| [API契約 v1](docs/api-contract-v1.md) | フロントエンドとFastAPIバックエンドの通信契約。イベント、検索、プロフィール、テーマ、GitHub連携、フィードバックのリクエスト／レスポンス |
| [データソース方針](docs/data-sources-mvp.md) | 取得可能なAPI・RSS一覧、MVPで採用する情報源、認証要件、イベント化の流れ、スクレイピングの境界、バックエンド実装順序 |
| [品質チェック詳細](docs/development-quality.md) | ktlint、Android Lint、pre-commit hook、GitHub Actionsの実行内容 |
| [セキュリティ監査結果（2026-08-21）](docs/security-audit-2026-08-21.md) | Android、任意バックエンド、OAuth、RSS、CI、依存関係の監査結果と対応優先順位 |

新たなAPIや情報源を追加する際は、まず「データソース方針」に取得条件・利用規約・根拠としての扱いを追記する。

## プロジェクト構成

```text
app/src/main/java/com/bulletfeed/app/
  data/          # デモデータ、Mock Repository（将来はRemote実装を追加）
  domain/        # Event、通知、Repository interfaceなど
  ui/
    BulletFeedViewModel.kt  # 画面共通の状態と更新処理
    onboarding/  # 初回プロフィール・テーマ・GitHub設定
    components/  # 共通Compose部品
    feed/        # フィード
    search/      # 検索
    detail/      # イベント詳細
    security/    # 脆弱性ダッシュボード・詳細
    notifications/ # 通知センター
    management/  # テーマ・GitHub連携・設定
backend/         # 任意利用のFastAPI参考実装（フロント単体でも動作）
```

`MockBulletFeedRepository` を将来の `RemoteBulletFeedRepository` に置き換えることで、Compose画面側を変更せずFastAPIへ接続できる構成です。
