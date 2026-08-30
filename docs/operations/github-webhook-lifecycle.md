# GitHub webhook lifecycle（M3 / #150）

GitHub webhook provisioningは、watched repositoryと同じ lifecycleで行う。hook secretの実値は
repositoryやCI artifactに保存せず、deployment secret managerから実行時だけ渡す。

## Provisioning procedure

1. watched repository追加後、既存 hook を `GET /repos/{owner}/{repo}/hooks` で確認する。
2. `config.url` が公開HTTPSの `/v1/webhooks/github` と一致する release hook がなければ、
   `events=["release"]`、`active=true`、`config.content_type="json"` で一つだけ作成する。
3. 既存 hook があれば作成せず、設定差分を監査する。endpoint identityやObservationの
   `source_key` は hook redirectや再登録で書き換えない。
4. secret rotationでは新secretをPATCHしてからdeliveryを確認し、旧secretをログ・report・
   responseへ出さない。
5. 最後の watch が削除された repositoryでは、release hookをDELETEする。共有管理hookを
   利用する場合は、他の watched repositoryが残る間は削除しない。

実行例（secret valueはshellへ直接書かず、secret managerの環境変数から注入する）:

```text
gh api --method POST repos/OWNER/REPOSITORY/hooks \
  -f name=web -f active=true -f 'events[]=release' \
  -f config[url]=https://PUBLIC_BACKEND/v1/webhooks/github \
  -f config[content_type]=json -f config[secret]=$GITHUB_WEBHOOK_SECRET
```

## Delivery and fallback

`X-GitHub-Delivery` はsanitized observability recordへ保持し、`/health/sources` の
`webhook` / `webhookAccepted` / `webhookIgnored` / `webhookSignatureFailures` countersで
delivery状態を監視する。署名不正は401、secret未設定は503とし、release以外の署名済みeventは
accepted-but-ignoredとして記録する。

Polling ingestはfallbackとして残る。webhookとpollingが同じreleaseを届けても、
Observationのsource identityとpayload hashによる既存idempotencyで重複Claimを作らない。
`backend/tests/test_github_webhooks.py` が署名、delivery ID、ignored event、duplicate delivery、
polling fallbackを外部GitHub通信なしで検証する。
