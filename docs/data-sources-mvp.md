# BulletFeed データソース方針（MVP）

更新日: 2026-08-18  
対象: 技術情報を追うソフトウェア開発者

## 1. 結論

MVPは一般ニュースを大量に集めない。**ユーザーの利用技術に結び付けられる一次情報**を優先し、次の4系統から始める。

1. GitHub連携リポジトリのRelease・依存関係
2. OSV / GitHub Advisoryの脆弱性情報
3. ユーザーが選択する公式RSS・公式更新履歴
4. 利用サービスのStatuspage

Hacker Newsなどのコミュニティ情報は、イベントの根拠ではなく「公式情報を探索する候補」の発見にのみ使う。

## 2. 優先データソース

| 優先 | 取得元 | 取得する変化 | このアプリでの用途 |
| --- | --- | --- | --- |
| P0 | GitHub Releases / Webhooks | SDK、ライブラリ、CLI、Actionのリリース | ユーザーが追うリポジトリや技術の更新 |
| P0 | GitHub SBOM | リポジトリの直接・間接依存関係とバージョン | 「使っているか」を判定する根拠 |
| P0 | OSV API | 利用依存関係に影響する脆弱性、修正版 | 直接影響のセキュリティイベント |
| P1 | GitHub Advisory Database | エコシステム別の公開セキュリティアドバイザリ | OSVとの相互補完、根拠URL |
| P1 | 公式RSS / Atom / Changelog | API廃止、料金、機能、規約、リリースノート | テーマに対する信頼できる変化 |
| P1 | Statuspage public API | 障害、復旧、予定メンテナンス | 継続するイベントの時系列 |
| P2 | Hacker News API | 新着・注目・更新された話題 | 一次情報を探すための候補発見 |

GitHubは公開リポジトリのReleaseを認証なしで取得でき、私有リポジトリはユーザー認可後に扱える。[GitHub Releases API](https://docs.github.com/en/rest/releases/releases)

GitHub連携したリポジトリでは、依存関係をSPDX形式のSBOMとしてエクスポートできる。SBOMにはパッケージ、バージョン、ライセンス、依存パスなどが含まれる。[GitHub SBOM API](https://docs.github.com/en/rest/dependency-graph/sboms)

OSV APIはパッケージ名・バージョンまたはPURL単位で脆弱性を照会でき、`POST /v1/querybatch` は複数依存関係をまとめて照会できる。[OSV API](https://google.github.io/osv.dev/api/)

GitHub Advisory Databaseは、公開アドバイザリをエコシステム（npm、Maven、PyPI、pubなど）で絞り込める。[GitHub Global Security Advisories API](https://docs.github.com/en/rest/security-advisories/global-advisories)

Atlassian Statuspageを使うサービスでは、公開ステータス、未解決インシデント、メンテナンス予定をページ単位のAPIで取得できる。[Statuspage API](https://status.atlassian.com/api/v2)

Hacker Newsは新着・トップ・更新済みのアイテムをAPIで取得できるが、投稿自体を事実の根拠にせず、必ず公式発表へ遡る。[Hacker News API](https://github.com/HackerNews/API)

## 3. 最初のテーマカタログ

デモと初期検証は、以下のテーマを標準候補にする。

- Kotlin / Android
- Cloudflare Workers
- OpenAI API
- GitHub
- Flutter

各テーマには原則として次の順で情報源を登録する。

1. 公式の変更履歴・リリースノート
2. 公式ブログのRSSまたはAtom
3. 関連するGitHubリポジトリのRelease
4. 利用サービスのStatuspage

## 4. 取得とイベント化の流れ

```text
Source Catalog
  ↓ 定期取得 / Webhook受信
Raw source snapshot（本文・取得日時・ETag・Last-Modified）
  ↓ 既存スナップショットとの差分
Change candidate（変更候補）
  ↓ 重複排除・イベント統合
Event
  ↓ GitHub SBOM / テーマ / プロフィールと照合
Relation: direct / adjacent / reference
  ↓ 重要度判定
Personalized Feed
```

## 5. 取得方式の指針

### GitHub

- Release取得はポーリングから開始する。
- 本番ではGitHub AppのWebhookで `release`、`push` などを受け、ポーリング頻度を下げる。GitHub Webhooksはイベント発生時に外部サーバーへ通知を配信できる。[GitHub Webhooks](https://docs.github.com/en/webhooks)
- GitHub OAuthの認可コード交換・アクセストークン保管はバックエンドだけで行う。Androidアプリは認可画面を開き、deep linkで結果を受け取る。

### RSS・更新履歴

- RSS/Atomがある場合は最優先する。
- RSSがない公式更新履歴は、利用規約と `robots.txt` を確認し、低頻度の条件付き取得（`ETag` / `Last-Modified`）を行う。
- 元文書、取得時刻、差分対象セクションを保存し、イベントには必ず根拠リンクを残す。

### Statuspage

- 対象サービスが公開しているStatuspage APIのみを利用する。
- `summary`、未解決incident、scheduled maintenanceを別々に保存し、同一incidentの状態遷移として統合する。

## 6. スクレイピングの境界

- 有料記事、ログイン必須コンテンツ、利用規約で禁止された自動取得は扱わない。
- 一般ニュースサイトからは、URL・タイトル・公開日時など許容された範囲だけを扱い、本文を恒久保存しない。
- 一次情報が見つからないイベントは、確信度を下げるかフィード候補から除外する。
- 各イベントに `source URL`、根拠文、取得日時、変換過程を保持する。

## 7. バックエンドへの最初の実装依頼

1. Source CatalogのCRUD（source種別、URL、テーマ、ポーリング間隔）
2. GitHub OAuth・対象リポジトリ選択
3. Release取得とRaw Snapshot保存
4. GitHub SBOM取得、PURL抽出、OSV `querybatch` 照合
5. イベント候補と根拠の永続化
6. フロントAPIの `Event` / `EventDetail` へ変換

この順なら、LLMによる高度な意味分類を後回しにしても、「自分の依存関係に影響するセキュリティ情報」と「追跡テーマの公式Release」を先に届けられる。
