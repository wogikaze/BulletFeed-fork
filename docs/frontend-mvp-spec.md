# BulletFeed フロントエンド MVP 仕様（ドラフト）

更新日: 2026-08-18  
対象: Android / Kotlin + Jetpack Compose

## 1. プロダクトの一文

ユーザーが追う技術・サービス・企業に起きた重要な変化を、**自分との関係**と**重要度**がひと目で分かる形で届けるパーソナライズド・イベントフィード。

記事一覧ではなく、複数の情報源を統合した「イベント」を読む。

## 2. MVP の対象ユーザー

技術情報を継続的に追うソフトウェア開発者。

## 3. 関連性の表示ルール

各イベントに次のいずれか一つを付与して表示する。

| 区分 | 意味 | UI 表現案 |
| --- | --- | --- |
| 直接影響 | 登録テーマ、または連携GitHubリポジトリで利用中の技術に明確に関係する | 赤紫の `直接影響` ラベル |
| 近接影響 | 関連技術、競合、所属業界などに関係する | 青の `近接影響` ラベル |
| 参考情報 | 興味には近いが、現時点で直接の対応は不要 | グレーの `参考` ラベル |

ラベルの近くに「なぜ表示されたか」を短文で常に示す。例: `GitHub上で使用中の Cloudflare Workers に関する変更`。

## 4. 重要度

重要度は `Critical / High / Medium / Low` の4段階とし、色だけに依存せず文字ラベルとアイコンでも表現する。

重要度の判断はバックエンドが担い、フロントは値・判断理由・確信度を表示する。

例:

- `Critical`: 期限付き廃止、セキュリティインシデント、利用不能につながる変更
- `High`: API・料金・互換性など、対応または意思決定が必要な変更
- `Medium`: 機能追加・ロードマップ・重要な正式発表
- `Low`: 関連する参考情報

## 5. 初期オンボーディング

### 5.1 プロフィール

- 職種（例: Android エンジニア）
- 興味（例: AI、モバイル、クラウド）
- 地域（任意）

### 5.2 追跡テーマ

- 技術、サービス、企業を5〜20件登録
- 候補検索・自由入力・削除ができる

### 5.3 GitHub連携

- OAuth連携を開始する導線
- 連携後、対象リポジトリをユーザーが選択
- 依存関係ファイルや使用言語を利用して関連性を高める
- 連携なしでもアプリ利用は可能

## 6. 主要画面

### フィード

- 上部: `すべて / 直接影響 / 近接影響 / 参考` フィルタ
- カード: 重要度、関連性、イベント名、変化の要約、表示理由、発表日時、根拠ソース数
- スワイプまたはメニュー: `重要`、`不要`、`既読`、`フォロー`
- 空状態: テーマ追加またはGitHub連携を促す

### イベント詳細

- 何が変わったか（変更前・変更後）
- 自分への関連理由
- 明示された影響と推定影響を区別して表示
- 時系列（発表、更新、追加情報）
- 根拠ソースのURL、引用箇所、取得日時
- フィードバックとフォローの操作

### テーマ・連携管理

- テーマの追加、削除、優先度調整
- GitHub連携状態、対象リポジトリの選択、解除
- プロフィール編集

## 7. フィードバックの意味

| 操作 | フロントでの結果 | バックエンドへの意味 |
| --- | --- | --- |
| 重要 | 保存済み表示、類似イベントを優先 | テーマ・イベント種別・ソースの重みを上げる |
| 不要 | カードをフィードから除外 | テーマ・イベント種別・ソースの重みを下げる |
| 既読 | 未読表示を解除 | 同一・類似更新を過剰に再通知しない |
| フォロー | イベントを監視中にする | 続報や状態変化を優先通知する |

`知っていた / 知らなかった` は初期MVPから外す。

## 8. バックエンドとの API 契約（フロント用 hooks）

認証方式などの詳細は後で決めるが、フロントは次の操作をインターフェースとして利用する。通信層を差し替え可能にし、初期開発では Fake 実装を使う。

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
}
```

バックエンドの対応エンドポイント案:

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
```

## 9. フロントエンド構成案

```text
app/
  data/          # API DTO、Repository実装、Fakeデータ
  domain/        # Event、Topic、ProfileなどのモデルとRepository interface
  ui/
    onboarding/
    feed/
    detail/
    settings/
    designsystem/
  navigation/
```

- UI: Jetpack Compose + Material 3
- 状態管理: ViewModel + StateFlow
- 非同期: Kotlin Coroutines
- DI: Hilt（導入のタイミングはプロジェクト作成時に決定）
- 通信: Retrofit / OkHttp を候補とし、初期は Fake Repository で画面を完成させる

## 10. MVP で扱わないこと

- 記事本文の収集、差分抽出、クラスタリング、重要度推定そのもの
- 通知の細かな最適化
- SNS上の話題収集
- 明示されていない因果の強い断定

これらはバックエンドの責務であり、フロントではイベント・根拠・影響分析結果を安全に分けて表示できる設計にする。
