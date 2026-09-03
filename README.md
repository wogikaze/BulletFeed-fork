# BulletFeed

追跡している技術・サービス・企業に起きた重要な変化を、**自分との関係**・**重要度**・**根拠**とあわせて届けるAndroidアプリです。MVPの中心は単なる記事一覧ではなく、ユーザーごとに「これまでに知っていた状態 → 意味のある差分 → その根拠」を成立させることです。

## 現在の実装

Androidアプリは `RemoteBulletFeedRepository` を通常の経路としてFastAPIバックエンドへ接続します。フィードはサーバー側の並び順とカーソルページングをそのまま利用します。カードから更新の詳細を開くと、変更前後、影響、タイムライン、根拠・情報源、元のURLを表示します。

フィードでは、意味のある表示だけを `/v1/feed/exposures` へ送信します。`viewport-exposure-v2` の条件は、1000ms以上かつ表示割合0.50以上、または詳細画面を開いた場合です。現在のAndroidアプリは滞在時間と表示割合を必ず送信し、値が欠けている場合は表示済みとして扱いません。バックエンドは条件を満たした表示に `KIND_DISPLAYED` を記録します。一瞬だけ画面に入った場合や、ごく一部しか見えていない場合は表示済みになりません。`GET /feed` を呼び出しただけでは既知にならず、配信済みと表示済みも区別します。

プロフィール、テーマ、優先度、並び順はサーバー側のパーソナライズに反映され、変更時には既存のフィードを再生成します。GitHub連携は実際のOAuth認証、リポジトリ選択、非公開リポジトリへのアクセス、セキュリティ警告、通知までバックエンドのAPI契約に接続しています。GitHubを使う初期設定は `profile -> github_pending -> repository_pending -> ready` の状態遷移で管理し、OAuth認証やリポジトリ選択を途中で離脱した状態を設定完了とは扱いません。

セッションはアクセストークンとローテーションするリフレッシュトークンで管理します。有効期限が切れた場合は同じBulletFeedアカウントのセッションを更新し、リフレッシュ用の認証情報を失った場合はGitHubアカウントを使った復旧へ進みます。既存アカウントを暗黙に新しい匿名アカウントへ置き換えることはありません。Android上のアクセストークン、リフレッシュトークン、OAuthポーリング用トークンは、Android Keystoreの鍵を使ったAES/GCM暗号化ストレージへ保存します。

フィードは、アプリがフォアグラウンドへ戻ったとき、フォアグラウンド中の定期更新、明示的な更新操作で再取得します。高度なプッシュ通知の最適化は、このMVPのリリース範囲には含めません。検索タブは現時点では**現在読み込まれているフィード内のローカル検索**であり、全更新履歴を対象にしたサーバー側検索ではありません。

`app/src/main/.../data` に残るMock/Demo実装は、テストデータとUI回帰テスト用です。通常のアプリ起動ではRemote Repositoryを生成します。Mockだけを使うMaestroフローは、実バックエンドを使った受け入れテストの代替にはなりません。

## Backend

`backend/` はAndroidアプリが利用する実バックエンドです。ローカル開発では次のように起動できます。

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

ローカルの `uvicorn` は、情報源の同期ワーカーを同じプロセスで起動します。これはテーマ追加後に公式RSSなどを取得するためのものです。`BULLETFEED_EMBED_SOURCE_SYNC_WORKER=0` で無効化できます。公開MVPでは `backend/compose.release.yml` がAPI、専用ワーカー、永続共有SQLiteボリューム、ワーカーのヘルスチェック、定期バックアップ処理を定義し、API側の組み込みワーカーは停止します。公開TLS、シークレット管理、バックアップの外部保管などを含む運用条件は [backend/RELEASE_OPERATIONS.md](backend/RELEASE_OPERATIONS.md) を参照してください。

公開環境ではUvicornの8000番ポートを直接インターネットへ公開しません。管理下のHTTPSオリジンを持つリバースプロキシまたはロードバランサーの背後に配置し、GitHubのコールバックも同じ公開HTTPS構成で設定します。

## Android起動

必要な環境はAndroid Studio、JDK 17、Android SDK Platform 36です。

Debug版の `BuildConfig.BASE_URL` は `http://10.0.2.2:8000/` です。`BulletFeedApiFactory.resolveBaseUrl` の扱いは次のとおりです。まずホスト側でバックエンドを `127.0.0.1:8000` で起動します。エミュレーターでは `10.0.2.2` をそのまま使い、ホスト上のバックエンドへ接続します。実機では `10.0.2.2` を `127.0.0.1` に置き換えるため、先に `adb reverse tcp:8000 tcp:8000` を実行します。平文HTTPを許可するのはDebug版だけです。

```bash
./gradlew :app:assembleDebug
```

ReleaseビルドではバックエンドURLを自動決定しません。管理下の公開HTTPSオリジンを明示しない限り、Releaseパッケージのビルドは失敗します。

```bash
BULLETFEED_RELEASE_BASE_URL=https://api.example.com/ ./gradlew :app:assembleRelease
```

`BULLETFEED_RELEASE_BASE_URL` には、HTTPS、localhost以外のホスト、末尾の `/` が必要です。Release版のmanifestでは平文通信を禁止します。

## 品質チェック

```bash
./gradlew ktlintCheck lint testDebugUnitTest
./gradlew :app:realBackendAcceptanceTest

cd backend
ruff check .
pytest -q
```

GitHub ActionsではAndroid quality、Backend quality、Backend security、Dependency lockを実行します。Mockを使うMaestroテストは、テストデータを使ったUI回帰テストです。MVPのDraft解除条件に使う実バックエンドの受け入れテストは [docs/real-backend-acceptance.md](docs/real-backend-acceptance.md) を参照してください。

## Security / data lifecycle

GitHubのアクセストークンはバックエンドで暗号化して保持し、GitHub連携を解除すると不要な認証情報を破棄します。設定画面からアカウントを削除すると、プロフィール、テーマ、評価・既知情報、フィードの状態、フォロー、GitHubの監視対象、セキュリティ警告、通知、セッションなど、そのユーザーに属するデータを削除します。

情報源の種類ごとに、信頼性、利用規約URL、コンテンツライセンス、生データ保持の可否、再配布、保持日数、非公開範囲、ポリシーバージョンを `source_policies` へ登録します。未登録の情報源が公開根拠テーブルへ入らないよう、未登録時は安全側に失敗させます。詳細は [backend/LEGAL_AND_SOURCE_POLICY.md](backend/LEGAL_AND_SOURCE_POLICY.md) と [backend/RELEASE_OPERATIONS.md](backend/RELEASE_OPERATIONS.md) を参照してください。

2026-08-21の監査文書は、当時のコミットを対象にした履歴です。現在のリリース運用との差分を確認した監査は [docs/security-audit-2026-08-23.md](docs/security-audit-2026-08-23.md) を参照してください。

## ドキュメント

| ドキュメント | 内容 |
| --- | --- |
| [フロントエンドMVP仕様](docs/frontend-mvp-spec.md) | 画面構成とComposeの責務 |
| [API契約 v1](docs/api-contract-v1.md) | AndroidとFastAPI間の通信契約 |
| [データソース方針](docs/data-sources-mvp.md) | MVPで扱う情報源、取得条件、根拠の扱い |
| [Release operations](backend/RELEASE_OPERATIONS.md) | API・ワーカー、永続ストレージ、準備状態、バックアップ・復元、ロールバック |
| [Real backend acceptance](docs/real-backend-acceptance.md) | Draft解除前に実バックエンドで行うE2E受け入れ手順 |
| [セキュリティ監査差分（2026-08-23）](docs/security-audit-2026-08-23.md) | セッション、Keystore、HTTPS、GitHub復旧、既知情報などの再評価 |

## プロジェクト構成

```text
app/src/main/java/com/bulletfeed/app/
  data/          # Remote adapter + fixture/mock helpers
  domain/        # Feed/Event/notification/API domain models and repository interfaces
  ui/            # Compose UI + ViewModel
backend/
  app/            # FastAPI, stores, source pipelines, sync worker
  compose.release.yml
  RELEASE_OPERATIONS.md
maestro/           # fixture-level UI regression only
```

新しいAPI、情報源、永続化方式、認証方式を追加するときは、API契約、情報源ポリシー、セキュリティ上の前提を同じ変更内で更新します。
