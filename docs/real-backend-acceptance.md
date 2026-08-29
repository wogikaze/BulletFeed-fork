# Real backend MVP acceptance

## Automated Android remote-client suite

JVM integration harness that drives production `BulletFeedApi` + `RemoteBulletFeedRepository` against an ephemeral local FastAPI + SQLite instance. Maestro mock fixtures are not this gate. No GitHub OAuth.

```bash
./gradlew :app:realBackendAcceptanceTest
```

Requires a backend Python environment with package extras installable as `pip install -e '.[dev]'` (or an equivalent venv that can import `app` and `uvicorn`). The task starts a 127.0.0.1 harness with `BULLETFEED_ACCEPTANCE_HARNESS=1`, then runs `RealBackendAcceptanceTest`.

Default `./gradlew :app:testDebugUnitTest` stays offline and excludes that class unless `-Pbulletfeed.acceptance.baseUrl=` is set.

---

この手順はPR #81系のDraft解除条件です。Mock Repository、固定demo seed、Mock初期状態のMaestro flowだけでは合格にしません。Android debug/release candidateと実FastAPI + source-sync workerを同じbackend contractで動かし、server stateを直接確認できるtest environmentで実施します。

## Preconditions

- Backend PR #83相当のcontractがfrontendの接続先へdeployされている。
- APIとsource-sync workerが同じdurable databaseを使用し、`GET /health/ready` が200。
- Android release candidateは所有HTTPS originを `BULLETFEED_RELEASE_BASE_URL` としてbuildし、cleartextを使用しない。
- GitHub test accountを用意し、少なくとも1つのpublic repositoryと、permission revokeを安全に試せるprivate repositoryへaccessできる。
- test accountの秘密情報やOAuth tokenをtest script、log、screenshot、repositoryへ保存しない。

## Required end-to-end chain

1. Clean installで起動し、初回sessionを作成する。backend上の`user_id`を記録する。
2. Profile/Topicsを設定し、GitHub modeを選ぶ。OAuth browserを閉じた場合にstateが`github_pending`のまま残り、再起動後もonboardingを再開できることを確認する。
3. GitHub OAuthを完了する。repositoryをまだ保存していない状態が`repository_pending`であり、main Feedへready遷移しないことを確認する。
4. public/private repositoryを選択して保存する。repository選択後にtopic inferenceが反映され、stateが`ready`になることを確認する。
5. source workerが取り込んだ実EventをFeedで表示する。Feed cardでtitle、importance、relation、timestamp、source publisher/provenanceが確認できること。
6. Feed pageを取得した直後、まだviewportへ表示していないdeliveryについて`user_claim_exposures`が増えていないことを確認する。実際にcardを表示し、`/feed/exposures`が成功したdeliveryだけcanonical claim knownnessへ反映されることを確認する。
7. 通信を一時的に失敗させてexposure POSTを失敗させ、同じprocess内でviewportを再表示したとき再送されることを確認する。失敗したdeliveryをclientがrecorded扱いしないこと。
8. Event detailを開き、opened/latest deltaのbefore/after、current state、impact、timeline、Evidence/Source、published/retrieved time、元URLがserver EventDetailと一致することを確認する。deep link `bulletfeed://event/{id}` からも同じdetailへ到達する。
9. follow/unfollow、read、important、not relevantを操作し、client-side optimistic fictionではなくserver再取得後の状態へ収束することを確認する。50件より後ろのpage itemでもread/feedbackが成功する。
10. cursor paginationを複数page進め、server orderingを保ち、重複itemを表示せず、cursorが進まない異常時に無限loadしないことを確認する。
11. Profile、Topic priority/orderを変更し、既存Feedのrelation/personalization rankがserver-sideで再projectionされ、同じold relationを読み直すだけでないことを確認する。
12. Security Alert一覧/detailを開き、notification targetからEvent/Security detailへ遷移する。対象が削除・permission lossになった場合は403/404でstale detailを画面に残さない。
13. Android processをkillして再起動する。token、pending OAuth state、selected IDs/deep-link navigationが必要な範囲で安全に復旧し、plaintext bearer/poll tokenがSharedPreferencesに存在しないことを確認する。
14. access token expiryを発生させ、rotating refresh tokenで**同じuser_id**へ戻ることを確認する。Profile、Topics、feedback、knownness、GitHub linkageが維持されること。
15. refresh credentialも利用できない状態を作り、GitHub identity recoveryを完了する。既存GitHub identityに紐づく**同じBulletFeed user_id**へ戻り、新しいanonymous userを作らないことを確認する。旧refresh token replayは401。
16. 選択private repositoryのGitHub permissionをrevocation相当にする。worker/APIがcredential/repository access lossを検出し、`reauthorization_required`へ収束すること。Androidは「connected」の通常repo UIで行き止まりにならず、同じBulletFeed userのGitHub再認証を提示する。
17. GitHubをdisconnectし、watchesが外れ、他userから参照されないupstream encrypted credentialが削除されることを確認する。private repository由来のアクセス不能Event/Alertがfrontendに残らないこと。
18. Settingsからaccount deletionを実行する。確認dialogなしに即削除されないこと。削除後はuser-scoped profile/topics/feed/deliveries/exposures/knownness/feedback/follows/watches/alerts/notifications/sessionsが残らず、旧access/refresh tokenで認証できないこと。
19. public HTTPS release candidateで上記主要chainを再度smokeし、`10.0.2.2`やHTTPへ接続していないことをnetwork inspectionで確認する。
20. API processを生かしたままworkerを停止し、`/health/ready`が503になることを確認する。worker再開後heartbeatがfreshになり200へ戻ることを確認する。backup jobを実行し、別test DBへのrestore drillを行う。

## Evidence to attach to the PR

秘密情報を含まない範囲で、使用したfrontend/backend commit SHA、Android build variant、public backend environment、各stepのpass/fail、`user_id`がrecovery前後で同一だったこと、knownness件数のbefore/after、permission-loss時のcredential state、CI run linksをPRへ残します。OAuth code、access/refresh token、GitHub upstream token、private repository本文は添付しません。

## Passing rule

全Required stepがpassし、Android quality / Backend quality / Backend security / Dependency lockがgreen、未解決P0/P1が0になった時だけPR #81のDraft解除候補とします。P2（global Event Search、高度なnotification optimization、大量source coverage等）はこのgateへ混ぜません。
