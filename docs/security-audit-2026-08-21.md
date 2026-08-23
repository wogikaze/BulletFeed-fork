# セキュリティ監査結果（2026-08-21）

> **Historical snapshot.** この文書はコミット `9bf0135289bbaded1b3f1b99f73b1832d9883042` 当時の監査記録であり、現行Android/backendの説明ではありません。その後Remote Repository、token永続化、deep link、session refresh/recovery、release HTTPS、GitHub credential state等が追加されています。現行release差分は [`security-audit-2026-08-23.md`](security-audit-2026-08-23.md) を参照してください。

## 概要

コミット `9bf0135289bbaded1b3f1b99f73b1832d9883042` を対象に、Androidフロントエンド、任意FastAPIバックエンド、GitHub OAuth、外部データ取得、CI、依存関係、秘密情報を静的解析とローカルテストで確認した。

検出結果は次のとおり。

| 重大度 | 件数 |
| --- | ---: |
| Critical | 0 |
| High | 0 |
| Medium | 0 |
| Low | 9 |

当時のバックエンドは `127.0.0.1` でのローカル検証用で、AndroidアプリもMock Repositoryを使用していた。この前提を考慮して全件をLowと評価した。**この評価を現行release候補へ適用してはならない。**

## 実行した確認

```bash
# Android
./gradlew :app:lintDebug

# Backend
ruff check .
pytest tests/test_security.py tests/test_rss_safety.py
```

- Android Lint: 成功
- Ruff: 成功
- 認証・RSS関連テスト: 6件成功
- GitHub、AWS、OpenAI等の実トークン・秘密鍵: 検出なし
- SQLクエリ: 確認範囲ではすべてプレースホルダーを使用

## 検出事項

| ID | 内容 | 主な場所 | 推奨対応 |
| --- | --- | --- | --- |
| SEC-01 | GitHub OAuthの結果が認証したAndroid installationへ結び付いていない | `backend/app/routers/auth.py` | installation固有鍵または認証済み端末へflowをbindし、結果取得時に証明させる |
| SEC-02 | 未認証のOAuth開始でSQLite行を無制限に作成でき、期限切れ行が削除されない | `backend/app/database.py` | rate limit、同時flow上限、期限切れ・完了flowの定期削除を追加する |
| SEC-03 | 古いBulletFeed sessionが再認証後のGitHub tokenも参照し、即時失効できない | `backend/app/database.py` | logout/revoke、`revoked_at`、credential generationを追加する |
| SEC-04 | 外部情報取得APIが未認証かつrate/concurrency limitなしで実行できる | `backend/app/routers/sources.py` | 認証、rate limit、同時実行上限、キャッシュ、RSS全体deadlineを追加する |
| SEC-05 | RSSのDNS検査結果が実際のHTTP接続先IPに固定されず、条件付きでDNS rebindingが可能 | `backend/app/services/rss.py` | 検査済みIPへ接続を固定し、接続先peer IPも再検査する |
| SEC-06 | 圧縮RSSを展開したchunkをサイズ確認前に確保するため、設定上限を超えてメモリを使用できる | `backend/app/services/rss.py` | 圧縮を拒否するか、圧縮前後の上限を持つbounded decompressorを使う |
| SEC-07 | GitHub Actionsが可変のmajor version tagを参照している | `.github/workflows/` | Actionsをレビュー済みの完全なcommit SHAへ固定する |
| SEC-08 | Python依存関係をlockfile・hashなしで毎回解決している | `backend/pyproject.toml` | 推移依存を含むlock/constraintsとhash検証を導入する |
| SEC-09 | Gradle distributionのSHA-256が固定されていない | `gradle/wrapper/gradle-wrapper.properties` | 公式の`distributionSha256Sum`を追加する |

## 当時問題が見つからなかった範囲

以下は2026-08-21時点の記録で、現行実装には該当しない記述を含む。

- Androidは`INTERNET` permission、deep link、WebView、通知用`PendingIntent`をまだ持っていなかった
- Android backupは無効になっていた
- launcher用`MainActivity`以外のexported componentはなかった
- Android側にtokenや秘密情報の永続保存・ログ出力はなかった
- GitHub access token、PKCE verifier、OAuth結果用tokenはバックエンドで暗号化またはhash化されていた
- OAuth stateはランダム生成され、期限と一回限りのcallback claimがあった
- RSSはHTTPS、443番port、host allowlist、private IP拒否、redirect再検査、Content-Type、本文サイズの基本制限を持っていた
- GitHub Actionsは`contents: read`で、`pull_request_target`やrepository secretを使用していなかった

## 当時の対応優先順位

公開バックエンドへ進める前に、次の順番で対応するとしていた。

1. SEC-01〜SEC-04: OAuth/session lifecycleとAPI abuse対策
2. SEC-05〜SEC-06: RSS取得境界の強化
3. SEC-07〜SEC-09: CIと依存関係の再現性・supply chain対策

現行のrelease gateと対応状況は2026-08-23監査差分および`docs/real-backend-acceptance.md`を参照する。

## 制約

- 実GitHubアカウントを使ったOAuth通信や本番環境への侵入テストは実施していなかった
- 当時はPython lockfileがなく、配備依存バージョン固有のCVEは確定していなかった
- `gradle-wrapper.jar`は構成と役割を確認したが、binary全体のsource auditは実施していなかった

この文書には秘密情報を含めない。新しい認証・ネットワーク・永続化機能を追加した場合は、公開前に再監査する。