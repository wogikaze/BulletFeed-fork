# BulletFeed Optional Backend

Androidフロントエンドの接続先として試せる、任意利用のFastAPIプロトタイプです。フロントエンド単体でもデモは動作するため、このディレクトリのセットアップは必須ではありません。

この実装はローカル開発・技術検証向けです。公開サービスへそのままデプロイする前に、永続DB、rate limit、監視、鍵管理、データ削除、OAuthセッションの失効・更新処理を追加してください。

## できること

- GitHub Appのユーザー認証（Authorization Code + PKCE + `state`）
- GitHubトークンのサーバー側暗号化保存
- 連携ユーザーがアクセス可能なリポジトリ一覧
- 公開リポジトリのGitHub Releases取得
- OSVによるパッケージ脆弱性照会
- 明示的に許可した公式RSS / Atomのプレビュー
- Atlassian Statuspageの公開ステータス取得

記事本文のクロール・転載、ログイン回避、有料記事取得、任意URLへのアクセスは実装していません。

## セットアップ

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

最後のコマンドの結果を `.env` の `BULLETFEED_TOKEN_ENCRYPTION_KEY` に設定します。`.env`、SQLiteデータ、GitHub資格情報はGit管理外です。

起動:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

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

Android Emulatorから接続するときは、APIのホストに `10.0.2.2:8000` を使います。OAuth callbackもエミュレータ内ブラウザから到達できるURLに合わせ、GitHub App側と `.env` の両方を同じ値へ変更してください。本番は所有ドメインのHTTPS callbackとVerified App Linksを使います。

## 認証フロー

1. Androidが `POST /v1/auth/github/start` を呼ぶ
2. `authorization_url` をCustom Tabで開き、`flow_id` と `poll_token` を一時保持する
3. GitHubがバックエンドの固定callbackへ戻す
4. Androidが `GET /v1/auth/github/status/{flow_id}` を `X-Auth-Poll-Token` 付きでポーリングする
5. `connected` のとき返る `app_access_token` をAndroid Keystoreで保護し、以降のBulletFeed APIでBearer tokenとして使う

GitHub access tokenはcallback URL、deep link、Androidレスポンスへ一度も載せません。現在のプロトタイプはrefresh tokenに未対応なので、GitHub user tokenが失効したら再認証が必要です。

## API例

```bash
curl -X POST http://127.0.0.1:8000/v1/auth/github/start

curl 'http://127.0.0.1:8000/v1/sources/github/releases?owner=JetBrains&repository=kotlin'

curl -X POST http://127.0.0.1:8000/v1/sources/osv/query \
  -H 'Content-Type: application/json' \
  -d '{"ecosystem":"Maven","package":"org.jetbrains.kotlin:kotlin-stdlib","version":"2.0.0"}'
```

RSSは `.env` の `BULLETFEED_RSS_ALLOWED_HOSTS` にあるホストだけ取得できます。HTTPS、標準ポート、公開IP、XML系Content-Type、1 MiB以下に制限し、リダイレクト先も再検査します。

## テスト

```bash
ruff check .
pytest
```

## 無料運用について

このローカル構成はSQLiteと公開APIを使うため、サーバー代やDB代は不要です。GitHub APIの未認証リクエストには低いレート制限があるため、認証済みアクセス、ETag、Webhook、キャッシュを追加し、過剰なポーリングは避けます。

取得元・保存範囲・スクレイピング禁止事項は [LEGAL_AND_SOURCE_POLICY.md](LEGAL_AND_SOURCE_POLICY.md) を参照してください。利用規約や法律への適合を保証する文書ではないため、公開運用前には対象サービスの最新規約を確認してください。
