# BulletFeed フロントエンド MVP 仕様（ドラフト）

更新日: 2026-08-18  
対象: Android / Kotlin + Jetpack Compose

## 1. プロダクト概要

BulletFeedは、ユーザーが追っている技術・サービス・企業の重要な更新を、**自分との関係**、**重要度**、**根拠**とともに届けるパーソナライズ型のフィードである。

単なる記事一覧ではなく、複数の情報源から得た内容を一つの更新としてまとめて表示する。

## 2. MVP の対象ユーザー

技術情報を継続的に追うソフトウェア開発者を主な対象とする。

## 3. 関連性の表示

各更新には、次のいずれか一つの関連度を表示する。

| 区分 | 意味 | UI 表現案 |
| --- | --- | --- |
| 直接影響 | 登録したテーマ、またはGitHub連携したリポジトリで利用中の技術に明確に関係する | `直接影響` ラベル |
| 間接影響 | 関連技術、競合製品、所属業界などを通じて関係する | `間接影響` ラベル |
| 参考情報 | 興味には近いが、現時点で直接の対応は必要ない | `参考` ラベル |

ラベルの近くには、表示された理由を短い文章で示す。例: `GitHubで利用中の Cloudflare Workers に関する更新`。

## 4. 重要度

重要度は `Critical / High / Medium / Low` の4段階とする。色だけに依存せず、文字ラベルやアイコンでも区別できるようにする。

重要度の判定はバックエンドが担当し、フロントエンドは判定結果と理由を表示する。

例:

- `Critical`: 期限付きの廃止、重大なセキュリティ問題、サービス停止につながる変更
- `High`: API、料金、互換性など、対応や意思決定が必要な変更
- `Medium`: 機能追加、ロードマップ、重要な正式発表
- `Low`: 関連する参考情報

## 5. 初期設定

### 5.1 プロフィール

- 職種（例: Androidエンジニア）
- 興味のある分野（例: AI、モバイル、クラウド）
- 地域（任意）

### 5.2 GitHub連携方法

- GitHubを連携して、利用技術からテーマを自動設定できる
- GitHubを使わず、テーマを手動で選ぶこともできる
- GitHubを連携する場合は、認証後に対象リポジトリを選択する
- 選択したリポジトリの使用言語、依存関係、設定ファイルなどを関連性判定に利用する

### 5.3 追跡テーマ

- 技術、サービス、企業を登録できる
- GitHub連携を使わない場合は5件以上を選択する
- 候補検索、自由入力、削除に対応する
- GitHub連携を使う場合は、選択したリポジトリからテーマを追加できる

初回設定は `プロフィール → GitHub連携方法 → 追跡テーマ` の3段階とする。完了した設定はバックエンドへ保存し、テーマ画面と設定画面から同じ状態を参照する。

## 6. 主要画面

### フィード

- 上部: `すべて / 直接影響 / 間接影響 / 参考` のフィルター
- カード: 重要度、関連度、更新名、要約、表示理由、発表日時
- メニュー: `重要`、`不要`、`既読`、`フォロー`
- 空の場合: テーマ追加またはGitHub連携を案内する

### 更新の詳細

- 現在の状態
- まだ確認していない事実
- 前回からの変更内容
- 明示された影響と推定される影響
- 時系列の更新履歴
- 根拠となる情報源とURL
- `重要`、`不要`、`フォロー` などの操作
- `知っていた`、`今知った` の記録

### セキュリティ

- GitHub連携したリポジトリの依存関係に該当する脆弱性を、通常のフィードとは分けて表示する
- `未対応 / 対応中 / 解決済み / 対象外` の対応状況を管理する
- 深刻度、対象リポジトリ、パッケージ、現在のバージョン、修正版、直接・間接依存を表示する
- GitHub Advisory、OSV、CVEなどの情報源と最終確認日時を表示する
- 緊急または重要で未対応の項目がある場合は、通常のフィードにも件数を表示してセキュリティ画面へ誘導する
- ソースコード本文は取得せず、依存関係のメタデータと公開済みのセキュリティ情報を照合する

### テーマ管理

- テーマの追加、削除、優先度変更、並び替え
- おすすめテーマと候補検索
- GitHub連携画面への導線

### GitHub連携

- GitHubとの連携状態を表示する
- 対象リポジトリを検索・選択する
- 選択したリポジトリから利用技術をテーマとして取り込む
- GitHub連携を解除できる

### 設定

- プロフィール編集
- 情報源の追加・削除
- サイトURLからRSS / Atom / JSON Feedを探す
- 既知として記録した内容を確認・リセットする
- 学習したフィード順をリセットする
- アカウントと保存データを削除する

### 通知

- フィード右上のベルに未読件数を表示する
- `セキュリティ / 重要な変更 / リリース` を文字と色で区別する
- 通知から更新の詳細または脆弱性の詳細へ直接移動する
- 個別既読と一括既読に対応する
- 通知には詳細データを持たせず、対象IDを使って認証済みAPIから取得する
- 非公開リポジトリ名などの機密情報はロック画面通知に表示しない

## 7. フィードバック

| 操作 | 画面上の結果 | バックエンドでの扱い |
| --- | --- | --- |
| 重要 | 重要な更新として記録 | 類似する更新の優先度調整に利用する |
| 不要 | フィードから除外 | 類似する更新の優先度調整に利用する |
| 既読 | 未読表示を解除 | 同じ内容の過剰な再表示を避けるために利用する |
| フォロー | 続報を追跡する | 状態変化や続報を優先して扱う |
| 知っていた | 既知だった内容として記録 | ユーザーの既存知識の推定に利用する |
| 今知った | 今回初めて知った内容として記録 | ユーザーの既存知識の推定に利用する |

## 8. バックエンドとの API 契約

フロントエンドは、通信方法の詳細ではなく次の操作をインターフェースとして利用する。通信層を交換できる構成にし、テストではFake実装を利用できるようにする。

```kotlin
interface BulletFeedRepository {
    suspend fun getFeed(filter: FeedFilter): List<Event>
    suspend fun getEvent(eventId: String): EventDetail
    suspend fun getProfile(): UserProfile
    suspend fun saveProfile(profile: UserProfile): UserProfile
    suspend fun getTopics(): List<Topic>
    suspend fun addTopic(name: String, type: TopicType): Topic
    suspend fun removeTopic(topicId: String)
    suspend fun getGithubConnection(): GithubConnection
    suspend fun startGithubConnection(): GithubAuthorization
    suspend fun updateGithubRepositories(repositoryIds: List<String>)
    suspend fun sendFeedback(eventId: String, feedback: FeedbackType)
    suspend fun setFollowing(eventId: String, following: Boolean)
    suspend fun getVulnerabilityAlerts(status: VulnerabilityStatus?): List<VulnerabilityAlert>
    suspend fun getVulnerabilityAlert(alertId: String): VulnerabilityAlert
    suspend fun updateVulnerabilityStatus(alertId: String, status: VulnerabilityStatus)
    suspend fun getOnboardingSnapshot(): OnboardingSnapshot
    suspend fun completeOnboarding(profile: UserProfile, topics: List<String>, connectGithub: Boolean): OnboardingSnapshot
    suspend fun updateTopics(topics: List<String>): List<String>
    suspend fun getNotifications(): List<AppNotification>
    suspend fun markNotificationRead(notificationId: String): AppNotification
    suspend fun markAllNotificationsRead(): List<AppNotification>
}
```

主なバックエンドAPIは次のとおり。

```text
GET    /v1/feed?relation=direct&status=unread
GET    /v1/events/{eventId}
GET    /v1/me/profile
PUT    /v1/me/profile
GET    /v1/me/topics
POST   /v1/me/topics
DELETE /v1/me/topics/{topicId}
GET    /v1/integrations/github
POST   /v1/integrations/github/authorize
PUT    /v1/integrations/github/repositories
POST   /v1/events/{eventId}/feedback
PUT    /v1/events/{eventId}/following
GET    /v1/me/security/alerts
GET    /v1/me/security/alerts/{alertId}
PATCH  /v1/me/security/alerts/{alertId}
PUT    /v1/me/onboarding
GET    /v1/me/notifications
PATCH  /v1/me/notifications/{notificationId}
POST   /v1/me/notifications/read-all
```

## 9. フロントエンド構成

```text
app/
  data/          # API DTO、Repository実装、テスト用データ
  domain/        # Event、Topic、ProfileなどのモデルとRepository interface
  ui/
    BulletFeedViewModel.kt
    onboarding/
    feed/
    detail/
    security/
    notifications/
    management/
```

- UI: Jetpack Compose + Material 3
- 状態管理: ViewModel + StateFlow
- 非同期処理: Kotlin Coroutines
- DI: 現在はViewModel Factoryを利用し、必要に応じてHiltを検討する
- 通信: Retrofit / OkHttp

## 10. MVP の範囲外

- 一般ニュースを網羅的に収集すること
- 通知配信の細かな最適化
- SNS上の話題を事実の根拠として扱うこと
- 根拠のない因果関係を強く断定すること

記事の取得、差分抽出、重複排除、更新の統合、重要度判定などはバックエンドの責務とし、フロントエンドはその結果を安全で分かりやすい形で表示する。
