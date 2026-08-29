# BulletFeed

追っている技術・サービス・企業に起きた重要な変化を、**自分との関係**・**重要度**・**根拠**と一緒に届けるAndroidアプリです。MVPの中心は、単なる記事一覧ではなく `previous known state -> meaningful delta -> evidence` をユーザーごとに成立させることです。

## 現在の実装

Androidは `RemoteBulletFeedRepository` を本線としてFastAPI backendへ接続します。Feedはserver ordering/cursor paginationをそのまま使い、カードからEvent detailへ遷移すると変更前後、impact、timeline、Evidence/Source、元URLを表示します。Feedで実際にviewportへ表示されたdeliveryだけを `/v1/feed/exposures` へ送り、backendがcanonical claim exposureをknownnessへ反映します。`GET /feed` しただけではknownになりません。

プロフィール・テーマ・priority/orderはserver-side personalizationへ反映され、変更時に既存Feedを再projectionします。GitHub連携は実OAuth、repository選択、private repository access、Security Alert、通知までbackend contractへ接続されています。GitHub onboardingは `profile -> github_pending -> repository_pending -> ready` のstate machineで、OAuthやrepository選択を途中離脱した状態をready扱いにしません。

セッションはaccess token + rotating refresh tokenです。期限切れ時は同じBulletFeed userをrefreshし、refresh credentialを失った場合はGitHub identity recoveryへ進みます。既存userを暗黙に新しい匿名userへ置き換えません。Android上のaccess/refresh/OAuth poll tokenはAndroid Keystore鍵によるAES/GCM暗号化ストレージへ保存します。

Feedはforeground復帰時、foreground中の定期更新、明示的な更新操作で再取得します。高度なpush notification最適化はMVPのこのrelease sliceには含めません。Searchタブは現時点では**現在ロード済みFeed内のローカル絞り込み**であり、全Event履歴を検索するserver-side Event Searchではありません。

`app/src/main/.../data` に残るMock/Demo実装はfixture・UI回帰用途です。通常のアプリ起動経路はRemote Repositoryを生成します。Mock-only Maestro flowはproduction backend acceptanceの代替ではありません。

## Backend

`backend/` はAndroidが依存する実backendです。ローカル開発では次のように起動できます。

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

継続取得にはAPIとは別にsource-sync workerが必要です。公開MVPでは `backend/compose.release.yml` がAPI + worker + durable shared SQLite volume + worker health + maintenance backup jobを定義します。公開TLS、secret management、backupのoff-host保管等を含む運用条件は [backend/RELEASE_OPERATIONS.md](backend/RELEASE_OPERATIONS.md) を参照してください。

公開releaseでUvicornの8000番portを直接internetへ露出しません。所有HTTPS originのreverse proxy/load balancerの背後へ置き、GitHub callbackも同じ公開HTTPS構成で設定します。

## Android起動

必要環境はAndroid Studio、JDK 17、Android SDK Platform 36です。

Debug buildはAndroid Emulator向けに `http://10.0.2.2:8000/` を使用し、debugだけcleartextを許可します。

```bash
./gradlew :app:assembleDebug
```

Release buildはbackend URLを暗黙に決めません。所有する公開HTTPS originを明示しない限りrelease package taskは失敗します。

```bash
BULLETFEED_RELEASE_BASE_URL=https://api.example.com/ ./gradlew :app:assembleRelease
```

`BULLETFEED_RELEASE_BASE_URL` はHTTPS、非localhost、末尾 `/` が必須です。release manifestではcleartext trafficを禁止します。

## 品質チェック

```bash
./gradlew ktlintCheck lint testDebugUnitTest
./gradlew :app:realBackendAcceptanceTest

cd backend
ruff check .
pytest -q
```

GitHub ActionsではAndroid quality、Backend quality、Backend security、Dependency lockを実行します。Mock Maestroはfixture-level UI regressionです。MVPのDraft解除条件として使うreal-backend acceptanceは [docs/real-backend-acceptance.md](docs/real-backend-acceptance.md) を参照してください。

## Security / data lifecycle

GitHub upstream tokenはbackendで暗号化して保持し、GitHub disconnectで不要なcredentialを破棄します。Settingsからのaccount deletionはprofile、topics、feedback/knownness、Feed state、follows、GitHub watches、Security Alert、notifications、sessions等のuser-scoped dataを削除します。

source kindごとにauthority、terms URL、content license、raw retention可否、redistribution、retention days、private scope、policy versionを `source_policies` へ登録し、未登録source kindがpublic evidence tableへ入ることをfail-closedにします。詳細は [backend/LEGAL_AND_SOURCE_POLICY.md](backend/LEGAL_AND_SOURCE_POLICY.md) と [backend/RELEASE_OPERATIONS.md](backend/RELEASE_OPERATIONS.md) を参照してください。

2026-08-21の監査文書は当時のcommitを対象にした履歴です。現行release lifecycleの監査差分は [docs/security-audit-2026-08-23.md](docs/security-audit-2026-08-23.md) を参照してください。

## ドキュメント

| ドキュメント | 内容 |
| --- | --- |
| [フロントエンドMVP仕様](docs/frontend-mvp-spec.md) | 画面構成とCompose責務 |
| [API契約 v1](docs/api-contract-v1.md) | Android / FastAPI間の通信契約 |
| [データソース方針](docs/data-sources-mvp.md) | MVP source、取得条件、evidence方針 |
| [Release operations](backend/RELEASE_OPERATIONS.md) | API/worker、durable storage、readiness、backup/restore、rollback |
| [Real backend acceptance](docs/real-backend-acceptance.md) | Draft解除前の実backend E2E受け入れ手順 |
| [セキュリティ監査差分（2026-08-23）](docs/security-audit-2026-08-23.md) | session、Keystore、HTTPS、GitHub recovery、knownness等の再評価 |

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

新しいAPI、source、永続化、認証方式を追加するときは、API contract・source policy・security assumptionsを同じ差分で更新します。