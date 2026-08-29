# BulletFeed API 契約 v1

更新日: 2026-08-29  
用途: Android公開API。Observation / Claim ledger / Semantic Delta 判定などの内部処理は公開しない。

## 1. 基本方針

- Base URL: `/v1`
- 形式: JSON (`Content-Type: application/json`)
- 日時: ISO 8601 UTC、例 `2026-08-18T10:30:00Z`
- 認証: `Authorization: Bearer <access-token>`
- 配列は空の場合も `[]`、任意値は `null`

公開モデルは Event / Delta / FeedItem / Evidence / Topic のみ。

- Event = 現実世界の同一の出来事
- Delta = Event内で新しく発生した意味上の変化
- FeedItem = そのユーザーに今回表示する Delta
- Evidence = 表示内容を裏付ける根拠
- Topic = ユーザーが追跡する技術・サービス・企業

`FeedItem.id` は安定した `userId × deltaId`。`deliveryId` は当該 `GET /feed` 応答の配信インスタンス。GET で FeedItem を作り直さない。

read/unread は Event ではなく FeedItem に持つ。

## 2. 列挙値

```text
Importance: critical | high | medium | low
RelationLevel: direct | adjacent | reference
DeltaType: new_fact | detail | state_update | correction | unresolved_contradiction
FeedItemStatus: unread | read
FeedbackType: important | not_relevant | follow | already_knew | learned_now | less_like_this | undo
EventPhase: investigating | identified | monitoring | resolved
TimelineType: announced | state_changed | information_added | corrected | resolved
SourceKind: statuspage | github_advisory | osv | github_release | github_sbom | rss_atom | json_feed | official_changelog | documentation
  (`official_changelog` / `documentation` は allowlist 公式HTMLの Observation/Claim ingest に使う。`generic_web` は discovery_only のまま Claim にしない)
TopicType: technology | service | company
TopicPriority: high | normal | low
```

NON_NOVEL な Delta は通常 FeedItem として配信しない。source 固有の investigating / identified は Timeline type に増やさず、`state.before/after` として保持する。

互換: 旧契約の `Event` カード、`FeedbackType.read`、`EventStatus.dismissed` は使わない。既読は `PUT /feed/items/{id}/read`。検索 API は作らない。SearchScreen は取得済みフィードのローカル検索。`/me/devices` は Push 導入まで作らない。

## 3. 公開モデル

### FeedItem

```json
{
  "id": "fi_usr_1_delta_workers_identified",
  "eventId": "workers-runtime",
  "delta": {
    "id": "delta_workers_identified",
    "type": "state_update",
    "summary": "旧ランタイム挙動の廃止期限と対象APIが公開されました。",
    "before": "旧ランタイム挙動が提供される。",
    "after": "2026年11月から新しい挙動へ移行する。",
    "occurredAt": "2026-08-18T03:00:00Z"
  },
  "title": "Cloudflare Workers の Node.js 互換性に破壊的変更予定",
  "importance": { "level": "high", "reason": "利用中APIに移行期限があるため", "confidence": "high" },
  "relation": {
    "level": "direct",
    "reason": "GitHubで連携したリポジトリが Cloudflare Workers を利用しています。",
    "matchedTopics": ["Cloudflare Workers"],
    "matchedRepositories": [
      { "id": "repo_123", "name": "niyu/example-worker", "url": "https://github.com/niyu/example-worker" }
    ]
  },
  "status": "unread",
  "following": false,
  "updatedAt": "2026-08-18T04:30:00Z",
  "deliveryId": "dlv_abc"
}
```

### EventDetail

```json
{
  "id": "workers-runtime",
  "title": "Cloudflare Workers の Node.js 互換性に破壊的変更予定",
  "summary": "旧ランタイム挙動が段階的に廃止されます。",
  "currentState": {
    "phase": "identified",
    "summary": "移行期限と対象APIが公開されています。",
    "since": "2026-08-18T03:00:00Z",
    "confidence": "high"
  },
  "latestDelta": { "id": "delta_workers_identified", "type": "state_update", "summary": "...", "before": "...", "after": "...", "occurredAt": "2026-08-18T03:00:00Z" },
  "openedDelta": null,
  "timeline": [
    {
      "id": "tl_workers_announced",
      "type": "announced",
      "occurredAt": "2026-08-18T03:00:00Z",
      "title": "変更を公式発表",
      "description": "移行期限と対象APIが公開されました。",
      "deltaId": "delta_workers_identified",
      "state": { "before": "investigating", "after": "identified" }
    }
  ],
  "impacts": [{ "kind": "explicit", "text": "対象APIの移行確認が必要です。", "confidence": "high" }],
  "sources": [
    {
      "publisher": "Cloudflare",
      "kind": "official_changelog",
      "title": "Node.js compatibility update",
      "url": "https://example.com/source",
      "publishedAt": "2026-08-18T03:00:00Z",
      "retrievedAt": "2026-08-18T03:05:00Z",
      "evidence": "対象APIの移行期限は2026年11月1日です。"
    }
  ],
  "following": false
}
```

`GET /events/{eventId}?fromFeedItem=` があるとき `openedDelta` を返す。crawl 方式などの内部情報は返さない。

## 4. エンドポイント

暫定認証: `POST /v1/sessions` → `{ accessToken, userId }`。外部 IdP 決定までローカルユーザーを発行する。GitHub は identity ではなく integration。

### Feed

`GET /feed?relation=&status=&cursor=&limit=`

- limit 1–50、既定 20
- 並び: `multiobjective-ranker-v1`（[ADR-0013](adr/0013-multiobjective-ranker-v1.md)）。軸は relevance（Relation）、importance/impact、novelty/knownness、redundancy penalty。未読はソートキーにしない。未読優先は `status=unread` かクライアント側ピン留め
- cursor: `v5|{policy_version}|{item_id}` を URL-safe Base64。同一 ranking version のあいだ安定。旧 cursor は `obsolete ranking version`
- 訂正と critical な security/incident は明示的な priority rule。同一 Event / redundancy group は多様性ペナルティ（削除しない）。不確実な knownness は hide しない
- 応答: `{ items: FeedItem[], nextCursor }`

`PUT /feed/items/{feedItemId}/read` — 当該 Delta を既読にする。詳細 GET では自動既読にしない。

`POST /feed/items/{feedItemId}/feedback` `{ type: important | not_relevant | follow | already_knew | learned_now | less_like_this | undo }`

Append-only ledger. Latest row wins per `(userId, feedItemId, type-family)`. `undo` writes a new row that supersedes the latest family for that item; history is retained.

Families:

- ranking: `important`, `not_relevant`
- knowledge: `already_knew`, `learned_now` (`learned_now` = did_not_know)
- follow: `follow`
- preference: `less_like_this`

Behavior:

- `important`: `marked_important`。フィードから消さない。既存互換
- `not_relevant`: その FeedItem だけを dismiss / 既読にする。既存互換
- `follow`: 当該 Event の `event_follows` を upsert。Claim / Event / Delta の事実は書き換えない
- `already_knew` / `learned_now`: ユーザー知識・パーソナライズ状態だけを更新する。Claim / Event / Delta / observation の正本は変更しない
- `less_like_this`: 受け付けて保存する。トピック全体の非表示や当該 item 以外の dismiss はしない
- `undo`: 直近 family の派生状態を取り消す。履歴行は消さない
- 同一シグナルの再送は派生状態として冪等（latest-state）。行は追加される
- 各行は取得できる範囲で `eventId` / `deltaId` / `claimId` を保持する

`POST /feed/exposures` `{ items: [{ deliveryId, displayedAt }] }`

- Claim knownness は `delivered` / `displayed` / `read`
- `GET /feed` は delivery と `delivered` を書く。watermark（再投影抑制）は `displayed` または `read` だけが進める
- 未表示の item は bounded retry（既定 3 回）後に GET から外れるが、`delivered` だけでは permanently known にしない
- 未知 `deliveryId` は無視、バッチ上限 50、`deliveryId` で冪等。複数端末の同一 `claim` は先勝ち

### Event

`GET /events/{eventId}`  
`PUT /events/{eventId}/following` `{ following }`  
存在しない、または閲覧できない ID は 404。

### User / Topics

`GET /me` → `onboardingCompleted, profile, topicCount, githubConnected`  
`GET/PUT /me/profile` fields: `occupation, interests[], region`  
`GET/POST /me/topics` `DELETE /me/topics/{topicId}` `PATCH /me/topics/{topicId}` `{ priority?, order? }`  
`GET /topics/search?q=` カタログ検索。自由入力の POST は残す。  
`GET /me/topic-recommendations?limit=&includeFollowed=` 認証済みのトピック推薦。検索ではない。トピックを自動追加しない。  
`PUT /me/onboarding` は既存 Android 用。profile 必須 + topics 5件以上。

### Knowledge bootstrap

既存知識の明示シード。BulletFeed 配信・表示・既読とは別 provenance。第三者履歴は暗黙 import しない。

`GET /me/knowledge/bootstrap` — 当該ユーザーの bootstrap 要約と証跡。空でも 200。

`POST /me/knowledge/bootstrap/claims` `{ claimIds[], sessionId? }` — ユーザーが既知と確認した claim。存在しない claim は 422。

`PUT /me/knowledge/bootstrap/checkpoint` `{ subjectKind: event|topic|global, subjectId, asOf?, catchUp? }`  
`asOf` 時点で既に真の claim だけを既知にする。後続の中間状態は既知にしない。`catchUp=true` は時刻だけ残す。

`DELETE /me/knowledge/bootstrap` — bootstrap 証跡だけ消す。delivery / feedback / follow baseline と Event/Claim/Delta は残す。

低信頼の inferred bootstrap は hide しない。他人の bootstrap は見えない。

`GET /me/topic-recommendations`

- limit 1–20、既定 10。`includeFollowed` 既定 true（追跡済みは `alreadyFollowed` で明示）
- 並び: score desc, name
- 応答: `{ version, policyVersion, cohort, items: TopicRecommendation[] }`
- `version`: `topic-recommendations-v1`
- `policyVersion`: `cold-start-v1`（Rec-11 版付きフォールバック）
- `cohort`: `empty_profile` | `profile_only` | `topic_selected` | `github_connected` | `history_rich`
- 各 item: `id, name, type, score, reason, provenance, alreadyFollowed, confidence, sourceSignals`
- `provenance`: `explicit`（宣言済み興味）または `inferred`（隣接・リポジトリ推定・catalog fallback）
- 空プロファイルは catalog fallback。`provenance=inferred`、reason に catalog と記す。explicit にはしない
- GitHub 由来 prior はフィードバック履歴を必要としない。catalog 人気は明示的興味を上回らない
- 最初の 1 件のフィードバックは bounded overlay。嗜好状態を置き換えない
- トピックを自動 follow しない。ledger / topics を書き換えない。Hard-negative（React ユーザーへの reactor 等）は返さない

### GitHub

`GET /me/integrations/github` — 接続状態のみ。repo 全件は載せない。  
`POST /me/integrations/github/authorize` — OAuth 開始。token は返さない。既存 poll flow を再利用。  
`GET /me/integrations/github/repositories?q=&cursor=&limit=`  
並び: `updatedAt desc, id desc`  
`PUT /me/integrations/github/repositories` `{ repositoryIds }`  
応答: 接続状態 + `addedTopics` / `alreadyTrackedTopics`。監視repo保存時に技術テーマを同期する。  
`DELETE /me/integrations/github` — 監視選択を消し接続を切る。フィード履歴は残す。

### Source subscriptions

認証必須。テナント分離。プレビュー用 `/v1/sources` とは別経路。任意 HTML は扱わない。

`GET /me/sources` — 当該ユーザーの Statuspage / RSS / Atom / JSON Feed 購読。

`POST /me/sources` `{ kind: statuspage | rss_atom | json_feed, url?, pageId? }`

- `statuspage`: `pageId`（`[a-z0-9]{8,32}`）または `*.statuspage.io` URL
- `rss_atom` / `json_feed`: HTTPS URL。`validate_feed_url` と `rss_allowed_hosts` で SSRF/allowlist を **保存・スケジュール前** に検証する
- 正規化は source registry（`canonicalize_url` + `find_duplicate_endpoint`）。同一正規ソースの再追加は冪等（既存なら 200、新規なら 201）
- 追加は `source_sync_subscriptions.selected=1` と `source_sync_jobs` を確定的に更新する
- 応答は安全なメタデータと同期状態のみ。他ユーザーの `source_key` は返さない

```json
{
  "id": "ep_…",
  "kind": "rss_atom",
  "canonicalUrl": "https://example.com/feed.xml",
  "pageId": null,
  "publisher": { "slug": "example.com", "displayName": "example.com" },
  "status": {
    "selected": true,
    "state": "pending",
    "lastSuccessAt": null,
    "lastAttemptAt": null,
    "failureCount": 0,
    "nextRunAt": "2026-08-29T07:50:00Z"
  }
}
```

`DELETE /me/sources/{subscriptionId}` — 当該ユーザーの購読を外す。最終購読者なら `selected=0` にし、有効リース中でなければ `source_sync_jobs` を消す。Observation 履歴は消さない。他人の購読 ID は 404。

### Security / Notifications

既存のまま残す。脆弱性は Event に統合しない。

`GET/PATCH /me/security/alerts`  
`GET /me/security/alerts/{alertId}`  
`GET/PATCH /me/notifications`  
`POST /me/notifications/read-all`

## 5. エラー

```json
{ "error": { "code": "validation_error", "message": "topic name is required", "field": "name" } }
```

| Status | code |
| --- | --- |
| 400 / 422 | validation_error |
| 401 | unauthorized |
| 403 | forbidden |
| 404 | not_found |
| 429 | rate_limited |
| 5xx | internal_error |
