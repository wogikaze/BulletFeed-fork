# BulletFeed API 契約 v1（ドラフト）

更新日: 2026-08-18  
用途: Androidクライアントとバックエンド間の実装契約。MVPではクライアントの `FakeBulletFeedRepository` がこの形のデータを返す。

## 1. 基本方針

- Base URL: `https://api.example.com/v1`
- 形式: JSON (`Content-Type: application/json`)
- 日時: ISO 8601 UTC、例 `2026-08-18T10:30:00Z`
- ID: 文字列UUIDまたは同等の一意な文字列
- 認証済みエンドポイント: `Authorization: Bearer <access-token>`
- 配列は空の場合も `[]`、任意値は `null` を返す

> 認証基盤・ページネーション形式は未決定。ここではモバイルフロントの実装に必要な最小契約を定義する。

## 2. 列挙値

```text
Importance: critical | high | medium | low
RelationLevel: direct | adjacent | reference
EventStatus: unread | read | dismissed
FeedbackType: important | not_relevant | read
TopicType: technology | service | company
SourceType: official_blog | release_note | github_release | rss | documentation
TimelineEntryType: announced | updated | incident | resolved | related_report
```

## 3. 共通モデル

### Event（フィードカード）

```json
{
  "id": "evt_cloudflare_workers_20260818",
  "title": "Cloudflare Workers: Node.js互換性の破壊的変更を予告",
  "summary": "一部のNode.js互換APIは2026年11月から新しいランタイム挙動へ移行します。",
  "importance": "high",
  "importanceReason": "利用中のAPIに互換性変更と移行期限があるため",
  "relation": {
    "level": "direct",
    "reason": "GitHubで連携したリポジトリが Cloudflare Workers を利用しています。",
    "matchedTopics": ["Cloudflare Workers"],
    "matchedRepositories": [
      { "id": "repo_123", "name": "niyu/example-worker", "url": "https://github.com/niyu/example-worker" }
    ]
  },
  "announcedAt": "2026-08-18T03:00:00Z",
  "updatedAt": "2026-08-18T04:30:00Z",
  "sourceCount": 2,
  "status": "unread",
  "following": false
}
```

### EventDetail

`Event` の全フィールドに加え、詳細画面用の情報を返す。

```json
{
  "id": "evt_cloudflare_workers_20260818",
  "title": "Cloudflare Workers: Node.js互換性の破壊的変更を予告",
  "summary": "一部のNode.js互換APIは2026年11月から新しいランタイム挙動へ移行します。",
  "importance": "high",
  "importanceReason": "利用中のAPIに互換性変更と移行期限があるため",
  "relation": {
    "level": "direct",
    "reason": "GitHubで連携したリポジトリが Cloudflare Workers を利用しています。",
    "matchedTopics": ["Cloudflare Workers"],
    "matchedRepositories": []
  },
  "announcedAt": "2026-08-18T03:00:00Z",
  "updatedAt": "2026-08-18T04:30:00Z",
  "sourceCount": 2,
  "status": "unread",
  "following": false,
  "change": {
    "before": "Node.js互換性フラグによって旧ランタイム挙動が提供される。",
    "after": "新しいランタイム挙動へ段階的に移行し、旧挙動は廃止予定。",
    "effectiveAt": "2026-11-01T00:00:00Z"
  },
  "impacts": [
    {
      "kind": "explicit",
      "text": "対象APIを利用するアプリケーションは移行確認が必要です。",
      "confidence": "high"
    },
    {
      "kind": "inferred",
      "text": "連携リポジトリの依存関係を更新する必要が生じる可能性があります。",
      "confidence": "medium"
    }
  ],
  "timeline": [
    {
      "id": "timeline_001",
      "type": "announced",
      "occurredAt": "2026-08-18T03:00:00Z",
      "title": "変更を公式発表",
      "description": "移行期限と対象APIが公開されました。"
    }
  ],
  "sources": [
    {
      "id": "src_001",
      "type": "official_blog",
      "publisher": "Cloudflare",
      "title": "Node.js compatibility update",
      "url": "https://example.com/source",
      "publishedAt": "2026-08-18T03:00:00Z",
      "retrievedAt": "2026-08-18T03:05:00Z",
      "evidence": "対象APIの移行期限は2026年11月1日です。"
    }
  ]
}
```

### UserProfile / Topic / GitHubConnection

```json
{
  "profile": {
    "occupation": "Androidエンジニア",
    "interests": ["モバイル", "AI", "クラウド"],
    "region": "東京"
  },
  "topic": {
    "id": "topic_001",
    "name": "Kotlin",
    "type": "technology",
    "createdAt": "2026-08-18T00:00:00Z"
  },
  "githubConnection": {
    "connected": true,
    "accountLogin": "niyu",
    "repositories": [
      { "id": "repo_123", "name": "niyu/example-worker", "fullName": "niyu/example-worker", "selected": true, "url": "https://github.com/niyu/example-worker" }
    ]
  }
}
```

## 4. エンドポイント

### フィードを取得

`GET /feed`

Query parameters:

| 名前 | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| `relation` | `direct \| adjacent \| reference` | 任意 | 関連性で絞り込み |
| `status` | `unread \| read` | 任意 | 既読状態で絞り込み |
| `cursor` | string | 任意 | 次ページ取得用 |
| `limit` | integer | 任意 | 1〜50、既定20 |

```json
{
  "items": [/* Event */],
  "nextCursor": "cursor_next_or_null"
}
```

フィードの既定順は、`critical/high` かつ未読のイベントを優先し、その後は `updatedAt` の降順とする。

### イベント詳細を取得

`GET /events/{eventId}`

Response: `EventDetail`

`404` はイベントが存在しない、または閲覧権限がない場合に返す。

### プロフィールを取得・更新

`GET /me/profile` → `UserProfile`

`PUT /me/profile`

```json
{
  "occupation": "Androidエンジニア",
  "interests": ["モバイル", "AI", "クラウド"],
  "region": "東京"
}
```

Response: 更新後の `UserProfile`

### テーマの一覧・追加・削除

`GET /me/topics` → `{ "items": [/* Topic */] }`

`POST /me/topics`

```json
{ "name": "Kotlin", "type": "technology" }
```

Response: `201 Created` + `Topic`

`DELETE /me/topics/{topicId}` → `204 No Content`

制約: MVPでは1ユーザーにつき5〜20テーマを推奨するが、技術的な上限はバックエンド側で決定する。

### GitHub連携

`GET /me/integrations/github` → `GitHubConnection`

`POST /me/integrations/github/authorize`

```json
{ "redirectUri": "bulletfeed://oauth/github/callback" }
```

```json
{ "authorizationUrl": "https://github.com/login/oauth/authorize?..." }
```

> モバイルアプリは `authorizationUrl` をカスタムタブで開き、バックエンドはOAuth完了後に指定のdeep linkへ戻す。トークンをクライアントへ返さない。

`PUT /me/integrations/github/repositories`

```json
{ "repositoryIds": ["repo_123", "repo_456"] }
```

Response: 更新後の `GitHubConnection`

### 評価を送る

`POST /events/{eventId}/feedback`

```json
{ "type": "important" }
```

Response:

```json
{ "eventId": "evt_cloudflare_workers_20260818", "feedback": "important", "status": "read" }
```

- `important`: 学習用評価。イベントをフィードから消さない
- `not_relevant`: フィードから除外する。再表示には設定画面または将来の履歴画面を用いる
- `read`: 既読状態にする

### フォロー状態を更新

`PUT /events/{eventId}/following`

```json
{ "following": true }
```

Response:

```json
{ "eventId": "evt_cloudflare_workers_20260818", "following": true }
```

## 5. エラー形式

すべてのエラーは以下の形式で返す。

```json
{
  "error": {
    "code": "validation_error",
    "message": "topic name is required",
    "field": "name"
  }
}
```

クライアントが最低限扱うHTTPステータス:

| Status | 取り扱い |
| --- | --- |
| `400 / 422` | 入力内容を修正するよう表示 |
| `401` | 再ログインへ誘導 |
| `403` | 権限がないことを表示 |
| `404` | 削除済みなどとして一覧に戻す |
| `429` | 少し時間を置いて再試行 |
| `5xx` | 再試行ボタン付きのエラー状態 |

## 6. フロント実装上の取り決め

- リストのIDはすべてサーバー発行IDを使用し、タイトルをIDとして扱わない。
- `inferred` な影響は「推定」と明示して表示し、断定表現にしない。
- `sources.evidence` がないイベントは、根拠のない影響として表示しない。
- UIの重要度計算・関連性計算はしない。デモ時のみFakeデータに固定値を持たせる。
- API実装への差し替えは `BulletFeedRepository` の実装を Fake から Remote に変えるだけで完了する構成にする。
