# BulletFeed Backend

Android が本線で接続する FastAPI backend です。通常のアプリ起動経路は `RemoteBulletFeedRepository` 経由でこの API を使います。fixture / Mock Maestro は UI 回帰用であり、このディレクトリの代替ではありません。

ローカル開発と公開構成の前提は異なります。公開 TLS、secret、backup の off-host 保管などは [RELEASE_OPERATIONS.md](RELEASE_OPERATIONS.md) を参照してください。

## できること

- 匿名セッション発行（`POST /v1/sessions`）と rotating refresh（`POST /v1/sessions/refresh`）
- GitHub App のユーザー認証（Authorization Code + PKCE + `state`）と GitHub identity recovery
- GitHub トークンのサーバー側暗号化保存、連携リポジトリ選択、private repository access
- Security Alert と通知
- Feed の server ordering / cursor pagination、viewport exposure、profile 変更時の再 projection
- 公開リポジトリの GitHub Releases、SBOM、OSV、Statuspage、許可した RSS / Atom / JSON Feed の取得（継続取得は API とは別の source-sync worker）

記事本文のクロール・転載、ログイン回避、有料記事取得、任意 URL へのアクセスは実装していません。Webhook 受信は公開 MVP の shipped 機能ではありません。

## セットアップ

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

最後のコマンドの結果を `.env` の `BULLETFEED_TOKEN_ENCRYPTION_KEY` に設定します。`.env`、SQLite データ、GitHub 資格情報は Git 管理外です。

起動:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

継続取得には API とは別に source-sync worker が必要です。公開 MVP では `compose.release.yml` が API + worker + durable shared SQLite volume を定義します。

- ヘルスチェック: `http://127.0.0.1:8000/health`
- OpenAPI UI: `http://127.0.0.1:8000/docs`

## GitHub Appの登録

GitHubの `Settings > Developer settings > GitHub Apps > New GitHub App` から開発用Appを1つ作ります。

推奨設定:

1. Homepage URL: BulletFeedの説明ページまたはローカル開発用URL
2. Callback URL: `.env` の `BULLETFEED_GITHUB_CALLBACK_URL` と完全一致させる
3. Request user authorization during installation: 有効
4. Expire user authorization tokens: 有効
5. Webhook: MVPでは無効。後から使う場合はsecret検証を必須にする
6. Repository permissions: Metadata `Read-only`。依存関係取得を実装する時だけContents等を追加する
7. Install App: 自分のアカウントへ、監視したいリポジトリだけを選択してインストールする

作成後、Client IDとClient secretを `.env` に設定します。private key、client secret、GitHub tokenをAndroidアプリへ入れてはいけません。

Android debug の接続先はルート README と同じ1手順です。`BuildConfig.BASE_URL` は `http://10.0.2.2:8000/`、`BulletFeedApiFactory` は Emulator ではそのホストを使い、実機では `127.0.0.1` に置換します。実機では `adb reverse tcp:8000 tcp:8000` が必要です。OAuth callback も接続元のブラウザから到達できる URL に合わせ、GitHub App 側と `.env` を同じ値へ変更してください。本番は所有ドメインの HTTPS callback と Verified App Links を使います。

## 認証フロー

1. Androidが `POST /v1/auth/github/start` を呼ぶ
2. `authorization_url` をCustom Tabで開き、`flow_id` と `poll_token` を一時保持する
3. GitHubがバックエンドの固定callbackへ戻す
4. Androidが `GET /v1/auth/github/status/{flow_id}` を `X-Auth-Poll-Token` 付きでポーリングする
5. `connected` のとき返る access token と refresh token をAndroid Keystoreで保護する。期限切れ時は `POST /v1/sessions/refresh` で同じ BulletFeed user を維持する。refresh credential を失った場合は GitHub identity recovery へ進む

GitHub access tokenはcallback URL、deep link、Androidレスポンスへ一度も載せません。

## API例

```bash
curl -X POST http://127.0.0.1:8000/v1/sessions

curl 'http://127.0.0.1:8000/v1/sources/github/releases?owner=JetBrains&repository=kotlin'

curl -X POST http://127.0.0.1:8000/v1/sources/osv/query \
  -H 'Content-Type: application/json' \
  -d '{"ecosystem":"Maven","package":"org.jetbrains.kotlin:kotlin-stdlib","version":"2.0.0"}'
```

RSSは `.env` の `BULLETFEED_RSS_ALLOWED_HOSTS` にあるホストだけ取得できます。HTTPS、標準ポート、公開IP、XML系Content-Type、1 MiB以下に制限し、リダイレクト先も再検査します。

## テスト

リポジトリルート（CI と同じ）:

```bash
ruff check backend
pytest backend -q --tb=short
```

このディレクトリから:

```bash
ruff check .
pytest -q
```

## 無料運用について

このローカル構成はSQLiteと公開APIを使うため、サーバー代やDB代は不要です。GitHub APIの未認証リクエストには低いレート制限があるため、認証済みアクセスと過剰なポーリング回避を前提にします。

取得元・保存範囲・スクレイピング禁止事項は [LEGAL_AND_SOURCE_POLICY.md](LEGAL_AND_SOURCE_POLICY.md) を参照してください。利用規約や法律への適合を保証する文書ではないため、公開運用前には対象サービスの最新規約を確認してください。
