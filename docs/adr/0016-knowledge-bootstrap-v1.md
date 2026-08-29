# ADR-0016 既存知識の明示ブートストラップ v1

状態: Accepted  
版: `knowledge-bootstrap-v1`  
Issue: #56 (Known-08)

## Context

新規ユーザーは GitHub・ニュース・仕事などで既に多くの事実を知っている。BulletFeed の証跡は配信・表示・既読・明示フィードバック・フォロー baseline に偏るため、初期既知度が系統的に欠ける。第三者履歴を黙って取り込むとプライバシーと provenance を壊す。

## Options

1. 推定興味や GitHub 監視履歴を既知として扱う。
2. ユーザーが明示した事実と、時点付き current-state checkpoint だけを bootstrap 証跡として残す。
3. ブートストラップを持たず、利用中の `already_knew` だけに頼る。

## Decision

方針 2。新しい migration は作らない。`user_knowledge_evidence` に bootstrap 専用 kind を足す。

| kind | provenance | confidence | hide |
| --- | --- | --- | --- |
| `bootstrap_explicit` | `bootstrap` | high | 可（#53 合成後） |
| `bootstrap_claim` | `bootstrap` | high | 可（checkpoint の現時点事実） |
| `bootstrap_checkpoint` | `bootstrap_checkpoint` | high | 対象なし（マーカー） |
| `bootstrap_inferred` | `bootstrap_inferred` | low | 不可。demote まで |

- 第三者履歴は暗黙 import しない。
- checkpoint は `valid_at <= as_of` の現時点事実だけ。途中経過は既知にしない。
- `catch_up` は時刻だけ残し、claim を既知にしない。
- reset は bootstrap 行だけ消し、delivery / feedback / baseline と ledger は残す。
- `user_claim_exposures` は書かない。GET `/feed` だけで known にしない原則を保つ。

## Consequences

検査・reset API が `/v1/me/knowledge/bootstrap` に載る。#55 評価器は bootstrap 精度と unknown-but-hidden を独立に測れる。

## Rollback

kind を無視すれば replay は unknown に戻る。行削除で reset できる。
