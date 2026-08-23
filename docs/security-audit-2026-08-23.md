# セキュリティ監査差分（2026-08-23）

この文書は2026-08-21監査以降に追加されたRemote Android、session persistence、deep link、GitHub OAuth recovery、公開backend構成を対象にした差分監査です。旧監査を現在の実装説明として再利用しません。

## Release blockerとして対応した項目

### Android token storage

access token、refresh token、OAuth poll tokenは通常のSharedPreferencesへ平文保存しません。Android Keystore内のAES鍵でAES/GCM暗号化し、preferences側にはciphertextとIVだけを保存します。旧plaintext keyが存在する場合は読み出し後に暗号化領域へ移し、元keyを削除します。Keystore鍵を失った場合はcredentialを復号できないものとしてsame-user recoveryへ収束します。

### Network boundary

DebugはEmulator開発用の `http://10.0.2.2:8000/` を使用できますが、release packageは `BULLETFEED_RELEASE_BASE_URL` の明示を要求します。release URLはHTTPS、非localhost、非`.local`、末尾 `/` を検証し、release manifestではcleartext trafficを禁止します。公開backendはreverse proxy/load balancerでTLS終端し、Uvicornのportを直接internetへ公開しません。

### Session identity

`/v1/sessions` は初回anonymous user作成用です。既存userの期限切れ復旧にはrotating refresh tokenを使い、refresh credentialを失った場合はGitHub identity recoveryを使います。Androidは既存userIdを持つ状態で `/v1/sessions` を自動再実行しません。refresh tokenは一度rotateした旧tokenを再利用できません。

GitHub account recovery用OAuth flowは通常のuser-bound OAuth flowとpurposeを分けます。unbound flowは明示的なaccount-recovery purposeでなければcallback前にfail-closedで拒否し、任意のlegacy unbound stateからGitHub token exchangeへ進めません。

### GitHub credential lifecycle

BulletFeed identity linkageとGitHub upstream credential healthは別stateです。upstream credential失効、または選択private repositoryのaccess喪失は `reauthorization_required` へ収束し、Androidはdisconnectを強制せず同じBulletFeed userのまま再認証を提示します。GitHub disconnect時はuser watchesを外し、他userから参照されない暗号化upstream credentialを削除します。

### Knownness / exposure

`GET /v1/feed` はdeliveryを作りますがknownnessを確定しません。実際にviewportへ表示されたdeliveryだけをAndroidが `/v1/feed/exposures` へ送信し、serverが受理したcanonical claim exposureだけが `user_claim_exposures` に入ります。AndroidはPOST成功前にdeliveryをrecorded扱いせず、通信失敗後に再送できます。

### Account and data deletion

`DELETE /v1/me` はuser-scoped profile、topics、Feed state、deliveries/exposures、feedback/knownness、follows、GitHub watches、security alerts、notifications、sessions等を削除します。Android Settingsは破壊操作の確認dialogを経由します。

### Source policy and private evidence

source kindごとのauthority、terms URL、license、raw retention、redistribution、retention days、private scope、policy versionをDBへ登録します。未登録source kindは `event_sources` へのinsertをrejectします。normalized evidenceの存在をsource raw contentの再配布許可とはみなしません。

## 継続して確認が必要な項目

- 公開originでのTLS設定、HTTP security headers、reverse proxy request limitsはdeployment infrastructureの実設定をrelease前に確認する。
- Keystoreのbackup/restore・端末交換時はsecretを復号できないため、GitHub identity recoveryを実機で確認する。
- 実GitHub accountでOAuth、private repository permission revoke、token expiry相当を通すreal-backend acceptanceが必要。
- FCM等のbackground pushはこのMVP sliceでは未導入。Manifestへ通知permissionやpush receiverを追加する時点で再監査する。
- SQLite single-host構成はMVP運用用。multi-host/horizontal scaleへ進む場合はDB、locking、backup、secret distributionを再設計する。
- source `retention_days` はpolicy metadataとして永続化済みだが、将来raw-body storeを追加する場合は削除job/enforcementを別途必須とする。

## Release gate

公開releaseのsecurity gateは、Backend security、Dependency lock、Backend quality、Android qualityがgreenであることに加え、`docs/real-backend-acceptance.md` のsession recovery、GitHub permission loss、account deletionを含む実backend flowを通すことです。Mock Repository / fixture Maestroだけではsecurity acceptance完了としません。
