# 1週間 field 評価プロトコル（#327 / session-telemetry-v1）

版: `field-eval-protocol-v1`  
親: #158 / #327 / #151  
正本の指標: `GET /v1/me/feed-sessions/metrics`（ADR-0018、`backend/app/routers/session_telemetry.py`）

この文書は **1週間の実利用** で測る手順である。fixture・AI-silver・offline Gold を
field の正にしない。Gold / blind ラベルを読んで実装を合わせることも、
`completion_gate_pass=true` を手で書くことも禁止する。

開始は **1人でよい**。#327 の完了目標は **≥5人**（または同等の session 数）であり、
開始ゲートではない。5人未満の実行は開始成功であり、#327 完了ではない。

## 1. 正とする指標

サーバー側の集計だけを日記の正にする。生スクロール座標は保存されない。
`GET /feed` は session を開始しない。Feedback は Event / Claim / Delta / Observation を書き換えない。

| 指標 | 定義（実装） | field での読み |
| --- | --- | --- |
| `useful_card_rate` | `important` または `learned_now` の feedback 数 / `card_displayed` 数 | 表示カードのうち「役立った未知」と明示された割合 |
| `already_known_reshow_rate` | `already_knew` の feedback 数 / `card_displayed` 数 | 既知の再表示率 |
| `cards_to_useful_item` | 各 session で最初の useful feedback までに表示したカード数の平均 | 有用カードまでの手数。useful が無い session は分母に入らない |
| `feedback_response_rate` | feedback 数 / `card_displayed` 数 | 表示に対する明示応答率 |

`displayed_count == 0` のとき各 rate は `null` である。null を 0 に置き換えない。
不要表示の定量は `not_relevant` を含む feedback と、日記の qualitatively な「見逃し」で補う。
見逃しは telemetry に自動では入らない。日記に残し、Gold へ書き戻さない。

保持は 30 日。ユーザーはいつでも `DELETE /v1/me/feed-sessions` で自分の telemetry だけ消せる。
ledger は残る。

## 2. 同意（開始前に必須）

参加者は利用開始前に、次を理解したうえで同意する。同意なしに他人のアカウントを作らない。

収集するもの:

- session の開始・終了時刻
- 意味のある表示（`card_displayed`）、詳細閲覧、明示 feedback 種別、follow
- 集計指標（上表）

収集しないもの:

- 生スクロール座標、閲覧履歴の常時追跡、連絡先、第三者サービスからの暗黙 import

撤回:

- 参加者は期間中いつでも同意を撤回できる
- 撤回時は `DELETE /v1/me/feed-sessions` を実行し、204 を確認する
- 撤回後も feed / 既知登録 / Claim ledger は残る（世界事実と既知度は消えない）
- サーバー側は `BULLETFEED_SESSION_TELEMETRY_ENABLED=false` で新規記録を止められる。feed は動く

同意記録は「いつ・誰が・どの版の説明を読んだか」だけを運営側に残す。
token、`user_id`、生 outcome 行を公開 artifact に置かない。

## 3. 1週間の手順

前提（ソフトウェア）は他レーンの field-ready 条件に従う。公開 HTTPS と OAuth secret は
[人間ブロッカー](../operations/field-eval-human-blockers.md) であり、このプロトコルは代替しない。

### Day 0（開始日）

1. 同意を取る。1人開始なら運営者自身でよい。
2. 公開 HTTPS backend の `GET /health/ready` を確認する。fixture で代替しない。
3. `BULLETFEED_SESSION_TELEMETRY_ENABLED` が有効なことを確認する。
4. 署名済み release APK（`BULLETFEED_RELEASE_BASE_URL`）を入れる。
5. 興味・購読を日常どおり設定する。評価用に Gold を書き換えない。
6. 最初の session を開始する（Android foreground の既存経路、または `POST /v1/me/feed-sessions`）。
7. ベースラインとして `GET /v1/me/feed-sessions/metrics` を保存する（多くは空でよい）。

### Day 1–6（毎日）

日常利用として feed を開き、分かったら明示 feedback する。

- 新しく知れた: `learned_now`
- 重要: `important`
- すでに知っていた再表示: `already_knew`
- 不要: `not_relevant`

日記（telemetry の外）にだけ書いてよいもの:

- 見逃した重要情報（何を、どの source で後から知ったか）
- source 不足 / knownness 誤り / Relation 誤り / ranking 誤りの仮分類
- 利用おおよその分数（任意。座標は取らない）

毎日の終わりに、そのユーザーの metrics をファイルへ保存する。

```text
curl -sS -H "Authorization: Bearer $ACCESS_TOKEN" \
  "$BASE_URL/v1/me/feed-sessions/metrics" \
  > "field-metrics/day-${DAY}-p${PARTICIPANT}.json"
```

`user_id` をファイル名や集計キーにしない。参加者番号だけを使う。

### Day 7（締め）

1. 最終 `GET /v1/me/feed-sessions/metrics` を取る。
2. `python backend/scripts/aggregate_field_session_metrics.py` で参加者横断の加重平均を出す。
3. offline 指標（M1 useful proxy、M2/M6 family IU@10 など）と **方向だけ** 比較する。
   差を「Gold が間違っている」としてラベルを書き換えない。
4. 重大な field failure だけを具体 Issue に分解する。
5. 希望者は `DELETE /v1/me/feed-sessions` で telemetry を消す。

```text
curl -sS -X DELETE -H "Authorization: Bearer $ACCESS_TOKEN" \
  "$BASE_URL/v1/me/feed-sessions"
```

204 のあと、同じ token で metrics を取ると `sessionCount=0` になる。ledger は残る。

## 4. 完了の読み方

| 状態 | 意味 |
| --- | --- |
| 1人で Day 0 を開始した | field 開始。#327 は未完了 |
| ≥5人（または十分な session）で 1週間の4指標が揃った | #327 の数量ゲート候補 |
| offline との乖離メモがある | 報告材料。production 再調整の入力ではない |
| `completion_gate_pass=true` | **このプロトコルでは書かない。** M7 最終判定は field + 他 Mission 証跡の後 |

#318（既知度の人間照合）と #325 / #326 は同じ週に測ってよい。
ただし人間の自己申告を factual truth へ流用しない。

## 5. RC 証跡との関係

field 週の前後で current SHA の RC report を再生成する。手順は
[RC 証跡の再生成](../operations/rc-evidence.md)。
再生成は `pre_field_release_candidate` のまま残り、`completion_gate_pass` は false のままである。
field を回しただけでは M7 Completion Gate は PASS にならない。
