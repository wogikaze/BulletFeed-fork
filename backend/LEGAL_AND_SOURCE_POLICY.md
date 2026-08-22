# データ取得・法務ガードレール

この文書は実装上の安全策であり、法律相談ではありません。運用地域、対象サイト、利用目的によって条件は変わるため、公開サービス化・収益化の前には対象サービスの最新規約と必要に応じて専門家の確認が必要です。

## 採用する取得元

| 取得元 | 方法 | 保存するもの | 保存しないもの |
| --- | --- | --- | --- |
| GitHub | 公式REST API / GitHub App | repository ID、Releaseメタデータ、根拠URL | ソースコード本文、不要な個人情報 |
| OSV | 公開API | 脆弱性ID、対象package/version、更新日時 | 不要な全文コピー |
| 公式RSS / Atom | 配信者が公開するfeed | タイトル、URL、日時、最大500文字の配信要約 | 記事本文、画像、添付物 |
| Statuspage | 公開Status API | incident ID、状態、更新時刻、根拠URL | 管理APIの秘密情報 |

## 必須ルール

1. APIまたは配信者が明示的に公開したRSS / Atomを優先する。
2. 有料・ログイン必須・アクセス制御された情報を取得しない。
3. CAPTCHA、bot対策、robots、技術的制限を回避しない。
4. 記事全文を恒久保存・再配布しない。必要最小限のメタデータと短い要約、原典リンクを扱う。
5. 出典、原典URL、取得日時をイベントから辿れるようにする。
6. 各取得元の規約・レート制限・ライセンス変更を定期確認し、禁止または不明になった取得元を停止できるようにする。
7. 削除依頼、連携解除、アカウント削除時に関連する非公開データとtokenを削除できるようにする。
8. LLMの要約・影響推定は原文と区別し、推定であることと確信度を表示する。

## セキュリティ境界

- 任意URLをバックエンドから取得しない。RSSは運営側allowlistへ事前登録する。
- DNS解決後のprivate / loopback / link-local IPを拒否する。
- HTTPSのみ、レスポンスサイズ・時間・Content-Type・リダイレクト回数を制限する。
- HTMLはactive contentとして表示せず、プレーンテキスト化する。Android内WebViewでJavaScriptを実行しない。
- GitHub Appは最小権限と選択リポジトリのみ。token・secretはサーバー側で暗号化する。
- Webhook導入時は署名、配信IDの重複、timestamp、body sizeを検証する。

## Source Catalogに必要な項目

- source ID / 表示名 / 公式URL
- 取得方式（API / RSS / Webhook）
- 利用規約URL・確認日
- 許可された保存項目と保持期間
- レート制限・推奨取得間隔
- ETag / Last-Modified
- provenance上の信頼度
- 無効化フラグと停止理由
