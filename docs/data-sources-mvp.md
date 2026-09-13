# BulletFeed データソース方針（MVP）

更新日: 2026-08-18  
対象: 技術情報を追うソフトウェア開発者

## 1. 基本方針

MVPでは一般ニュースを大量に収集せず、**ユーザーが実際に利用している技術へ結び付けられる一次情報**を優先する。最初は次の4系統を中心に扱う。

1. GitHub連携したリポジトリのリリース情報と依存関係
2. OSV / GitHub Advisoryの脆弱性情報
3. ユーザーが選択した公式RSS・公式の変更履歴
4. 利用サービスのStatuspage

Hacker Newsなどのコミュニティ情報は、事実の根拠としては使わず、公式情報を見つけるための手掛かりとしてのみ利用する。

## 2. 利用するデータソース

| 優先度 | 取得元 | 取得する内容 | 認証 | BulletFeedでの用途 |
| --- | --- | --- | --- | --- |
| P0 | GitHub Releases API | SDK、ライブラリ、CLI、Actionなどのリリース | 公開リポジトリは不要、非公開リポジトリはGitHub連携が必要 | 追跡中のリポジトリや技術の更新 |
| P0 | GitHub Webhooks | release、push、advisoryなどの通知 | GitHub App | ポーリングを減らし、更新を早く検知する |
| P0 | GitHub SBOM API | 直接・間接依存するパッケージとバージョン | GitHub連携 | ユーザーが実際に利用している技術かを判断する |
| P0 | OSV API | 利用中の依存関係に影響する脆弱性と修正版 | 不要 | 直接影響するセキュリティ情報 |
| P0 | 公式RSS / Atom / Changelog | API廃止、料金改定、機能変更、規約変更、リリースノート | 通常不要 | 追跡テーマに関する信頼性の高い更新 |
| P0 | Statuspage API / RSS | 障害、復旧、予定メンテナンス | 公開ページは不要 | 障害など継続的に状態が変わる更新の追跡 |
| P1 | GitHub Advisory Database | エコシステム別の公開セキュリティ情報 | 基本不要 | OSVの補完と根拠URLの取得 |
| P1 | npm Registry API | npmパッケージの新しいバージョンと公開日時 | 不要 | JavaScript系の依存関係更新 |
| P1 | PyPI JSON API | Pythonパッケージの新しいバージョン | 不要 | Python系の依存関係更新 |
| P1 | Maven Central | Android / Kotlin / Javaライブラリの更新 | 不要 | Android開発者向けの依存関係更新 |
| P1 | Hacker News API | 新着・注目・更新された話題 | 不要 | 一次情報を探すための手掛かり |
| P1 | Stack Exchange API | 特定技術の新しい質問や注目Q&A | 不要 | 実際の利用者が遭遇している問題を把握する補助情報 |
| P2 | GDELT | 一般ニュースの検索・大量収集 | 不要 | 企業・地域テーマの候補発見。ノイズが多いため事実の根拠には使わない |

### MVPで扱う4系統

最初の実装は次の4系統に絞る。これにより、「自分の依存関係への影響」「公式な製品変更」「障害」を優先して扱える。

1. GitHub Releases / Webhooks
2. GitHub SBOM + OSV
3. ユーザーが選んだ公式RSS・変更履歴
4. 追跡サービスのStatuspage

パッケージレジストリ、Hacker News、Stack Exchange、GDELTは、更新の統合や関連性判定が安定してから追加する。コミュニティ情報や一般ニュースは、公式発表へのリンクを見つけるための手掛かりとして利用し、事実の根拠にはしない。

GitHubでは、公開リポジトリのリリース情報を認証なしで取得できる。非公開リポジトリは、ユーザーによるGitHub連携後に扱う。[GitHub Releases API](https://docs.github.com/en/rest/releases/releases)

GitHub連携したリポジトリでは、依存関係をSPDX形式のSBOMとして取得できる。SBOMにはパッケージ、バージョン、ライセンス、依存関係などが含まれる。[GitHub SBOM API](https://docs.github.com/en/rest/dependency-graph/sboms)

OSV APIでは、パッケージ名とバージョン、またはPURLを使って脆弱性を照会できる。`POST /v1/querybatch` を使うと複数の依存関係をまとめて照会できる。[OSV API](https://google.github.io/osv.dev/api/)

GitHub Advisory Databaseでは、公開されているセキュリティ情報をnpm、Maven、PyPI、pubなどのエコシステムで絞り込める。[GitHub Global Security Advisories API](https://docs.github.com/en/rest/security-advisories/global-advisories)

Atlassian Statuspageを利用するサービスでは、公開ステータス、未解決のインシデント、予定メンテナンスをページ単位のAPIから取得できる。[Statuspage API](https://status.atlassian.com/api/v2)

Hacker Newsは新着・トップ・更新済みの投稿をAPIから取得できる。ただし投稿自体を事実の根拠にはせず、必要に応じて公式発表まで確認する。[Hacker News API](https://github.com/HackerNews/API)

## 3. 初期テーマ

デモと初期検証では、次のテーマを標準候補とする。

- Kotlin / Android
- Cloudflare Workers
- OpenAI API
- GitHub
- Flutter

各テーマには、原則として次の順で情報源を登録する。

1. 公式の変更履歴・リリースノート
2. 公式ブログのRSSまたはAtom
3. 関連するGitHubリポジトリのリリース
4. 利用サービスのStatuspage

## 4. 取得からフィード表示まで

```text
Source Catalog
  ↓ 定期取得 / Webhook受信
Raw source snapshot（本文・取得日時・ETag・Last-Modified）
  ↓ 既存スナップショットとの差分
Change candidate（変更候補）
  ↓ 重複排除・更新の統合
Event
  ↓ GitHub SBOM / テーマ / プロフィールと照合
Relation: direct / adjacent / reference
  ↓ 重要度判定
Personalized Feed
```

上記の英語名は内部モデル名であり、利用者向け画面では対応する日本語を表示する。

## 5. 取得方法

### GitHub

- リリース情報の取得はポーリングから開始する。
- 本番ではGitHub AppのWebhookで `release`、`push` などを受け取り、ポーリング頻度を下げる。GitHub Webhooksはイベント発生時に外部サーバーへ通知を送信できる。[GitHub Webhooks](https://docs.github.com/en/webhooks)
- GitHub OAuthの認可コード交換とアクセストークンの保管はバックエンドだけで行う。AndroidアプリはGitHubの認証画面を開き、ディープリンクで結果を受け取る。

### RSS・変更履歴

- RSS / Atomがある場合は優先して利用する。
- RSSがない公式の変更履歴は、利用規約と `robots.txt` を確認したうえで、低頻度の条件付き取得（`ETag` / `Last-Modified`）を行う。
- 元文書、取得時刻、差分対象の箇所を保存し、更新には必ず根拠となるリンクを残す。

### Statuspage

- 対象サービスが公開しているStatuspage APIだけを利用する。
- `summary`、未解決のインシデント、予定メンテナンスを別々に保存し、同じインシデントの状態変化として統合する。

## 6. スクレイピングの範囲

- 有料記事、ログイン必須コンテンツ、利用規約で自動取得が禁止されているコンテンツは扱わない。
- 一般ニュースサイトでは、URL、タイトル、公開日時など許可された範囲の情報だけを扱い、本文を恒久保存しない。
- 一次情報が見つからない更新は、信頼度を下げるかフィード候補から除外する。
- 各更新には、情報源のURL、根拠となる内容、取得日時、変換過程を保持する。

## 7. バックエンドの実装順序

1. 情報源カタログのCRUD（種類、URL、テーマ、取得間隔）
2. GitHub OAuthと対象リポジトリの選択
3. リリース情報の取得と元データの保存
4. GitHub SBOMの取得、PURLの抽出、OSV `querybatch` との照合
5. 更新候補と根拠の永続化
6. フロントエンドAPIの `Event` / `EventDetail` 形式への変換

この順序で進めれば、LLMによる高度な意味分類を後回しにしても、「自分の依存関係に影響するセキュリティ情報」と「追跡テーマの公式リリース」を先に提供できる。
