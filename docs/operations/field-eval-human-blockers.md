# Field 評価の人間ブロッカー（#327 / #158）

エージェントは次を閉じない。fixture・local / emulator・clean-room backend で
代替したことにして `completion_gate_pass=true` にしない。

開始は **1人でよい**。以下が無いと field 週はローカルに落ち、M7 の field-readiness は
unmet のまま残る。#327 の完了目標 **≥5人** は、他人を集める作業を含む。

## エージェントが閉じられない項目

| ブロッカー | なぜ人間だけか | 無いときの結果 |
| --- | --- | --- |
| 常時起動の公開 HTTPS backend（ドメインと証明書） | 本番経路の field は公開オリジンを必要とする。local fixture は M7 が意図的に除外している | 実機が本番 URL に届かない。release APK の `BULLETFEED_RELEASE_BASE_URL` を検証できない |
| GitHub OAuth client secret | 本番 secret / credential。リポジトリにも CI artifact にも置かない | GitHub 連携が必要な参加者を登録できない。clean-room は live OAuth を含まない |
| 有料ホスティング契約 | 支払い・契約は AGENTS.md の人間限定ブロッカー | 常時公開スタックをエージェントが用意できない |
| 自分以外の実ユーザーの同意と登録 | 実ユーザーへの連絡・同意は人間限定。1人開始は運営者自身で足りる | #327 の ≥5人 完了目標に届かない。1人パイロットは開始として記録する |

## 開始してよいもの / 完了にしないもの

- 公開 HTTPS と OAuth secret が揃ったあと、運営者1人で Day 0 を開始してよい。
- 1人分の `GET /v1/me/feed-sessions/metrics` は開始証跡であり、#327 完了証跡ではない。
- ≥5人（または十分な session 数）は field 週の目標である。エージェントが他人を勧誘しない。
- 署名済み APK のビルド自体はソフトウェア作業だが、公開 URL と secret の投入は人間作業である。

## 参照

- 1週間手順: [field-eval-protocol.md](../evaluation/field-eval-protocol.md)
- Session 契約: [0018-session-telemetry-v1.md](../adr/0018-session-telemetry-v1.md)
- Clean-room が field を代替しないこと: [clean-room-acceptance.md](../evaluation/clean-room-acceptance.md)
