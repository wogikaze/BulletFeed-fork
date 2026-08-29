# Gold 人手ラベル手順（label-protocol-v1）

更新日: 2026-08-29  
プロトコル版: `label-protocol-v1`  
親 Issue: #36 / 本手順: #74  
後続データセットが採用する評価契約: #37（推薦）、#55（既知度）、#66（semantic-delta）

## 1. 目的

Relevance・user-importance・「ユーザーはすでにこれを知っているか」は部分的に主観である。手順のない Gold は、アノテータ間の揺れをアルゴリズム誤差として固定してしまう。

この文書は、製品価値 Gold の **評価契約** を定義する。

1. ラベルスキーマ（ラベル族と許容値）
2. 曖昧・文脈不足の扱い（無理にラベルを埋めない）
3. パイロット / ブラインドの分離
4. 二重ラベルと不一致の裁定
5. データセット版（旧 Gold をその場で書き換えない）

#37 / #55 / #66 は、この契約を後から採用する。本リポジトリの既存 Gold（`backend/tests/gold/v02/**` など）は書き換えない。

実装上の正本は `backend/app/evaluation/label_contract.py` と `label_contract_metrics.py` である。

## 2. ラベル族

| ラベル族 | 識別子 | 許容値 | 主な後続 Issue |
| --- | --- | --- | --- |
| relevance | `relevance` | 0–3 | #37 |
| user-importance | `user_importance` | 0–3 | #37 |
| semantic equivalence | `semantic_equivalence` | `equivalent` / `not_equivalent` / `uncertain` | #66 |
| novelty / revision class | `novelty_revision` | `NEW_FACT` / `DETAIL` / `STATE_UPDATE` / `CORRECTION` / `UNRESOLVED_CONTRADICTION` / `NON_NOVEL` | #66 |
| knownness / novelty-to-user | `knownness` | `already_knew` / `new` | #55 |
| should_surface | `should_surface` | `true` / `false` | #37, #55 |

1件のアノテーションは、対象アイテム（ユーザー×候補、または Claim 対）に対して、必要なラベル族だけを記録する。族をまたいで値を流用しない。事実世界の等価性（`semantic_equivalence` / `novelty_revision`）と、ユーザー個人の既知度（`knownness`）を混ぜない。

## 3. 曖昧・文脈不足

アノテータはラベルを無理に埋めず、次のいずれかを付けてよい。

| `ambiguous` | 意味 |
| --- | --- |
| `none` | 通常の確定ラベル。`value` 必須。 |
| `ambiguous` | 提示された情報では複数解釈が同程度に妥当。 |
| `insufficient_context` | ユーザープロファイル、事前既知、原文、対になる Claim などが欠けて判断不能。 |

`ambiguous` / `insufficient_context` のとき `value` は任意（仮置き可）。評価ツールは未裁定の曖昧件を採点から除外するか、別集計する（`filter_unresolved_ambiguous`）。曖昧フラグを「どちらでもない中間ラベル」の代わりに使わない。

正例: タイトルだけ提示され、ユーザーが当該リポジトリを watch しているか不明 → `relevance=insufficient_context`。  
負例: 迷ったので relevance=1 を「逃げ」として付ける。迷ったら曖昧にする。

## 4. パイロット / ブラインド

| split | 用途 |
| --- | --- |
| `pilot` | 手順の習熟、IAA 測定、開発中の回帰。 |
| `blind` | 開発者が日常的に見ない holdout。リリースゲート用。 |

パス規約: ブラインドコーパスは必ず `.../blind/` 配下に置く。`split=blind` またはそのパスを持つレコードは、本番採点コード（`load_annotations_for_production_scoring`）に読み込んではならない。ヘルパーは `is_blind_split`。

パイロットで手順やスキーマを変えたら、プロトコル版またはデータセット版を上げ、ブラインドを再ラベルするかを明示する。パイロットを見てブラインドを後付けで直さない。

## 5. 二重ラベルと一致度

代表サブセットは必ず二重ラベルする（`DoubleLabelRecord`）。同一アイテムを 2 人の独立したアノテータが、互いのラベルを見ずに付ける。

IAA はラベル族ごとに報告する（`compute_iaa`）。

- 一致率（percent agreement）
- Cohen's kappa
- 不一致件数
- 未裁定の曖昧件数（除外または別掲）

未裁定の `ambiguous` / `insufficient_context` は既定で IAA 分母から除外し、`unresolved_ambiguous_count` に数える。

## 6. 裁定（Adjudication）

不一致または曖昧が残った件は、第三者（または協議）が裁定する。裁定は履歴として残す（`AdjudicationRecord.adjudication_id`）。

禁止: 旧 Gold レコードをその場で上書きする。  
必須: 新しい `dataset_version` または overlay（`apply_adjudication` が `overlay:{adjudication_id}` を返す）。`source_dataset_version` のレコードは不変。

裁定後も元の二重ラベルは残す。IAA は裁定前ラベルで測る。

## 7. データセット版とマニフェスト

`DatasetManifest` は少なくとも次を記録する。

- `protocol_version`（本手順の版。いまは `label-protocol-v1`）
- `dataset_version`（コーパスの版。ラベル内容が変わったら上げる）
- `split`（`pilot` / `blind` / `mixed`）
- `provenance`（出典、作成者、生成方法）
- 任意で `parent_dataset_version`（overlay の親）

既存 v0.1 / v0.2 Gold を本手順で再ラベルする場合も、旧ファイルを書き換えず新版ディレクトリを追加する。

---

## 8. ラベル族の定義と例

以下、各ラベル族について正例と負例を示す。負例は「その値を付けてはいけないケース」である。

### 8.1 relevance（0–3）

対象: この候補は、提示されたユーザプロファイル・トピック・リポジトリに対して意味的に関係するか。重要度や既知度は見ない。

| 値 | 定義 |
| --- | --- |
| 0 | 無関係。語彙が偶然重なるだけを含む。 |
| 1 | 同じ業界・隣接製品など、弱い関連。 |
| 2 | ユーザーの技術領域に直接関係するが、今すぐの作業対象ではない。 |
| 3 | ユーザーが追跡する製品・依存関係・担当サービスそのもの。 |

正例（3）: ユーザーは `vercel/next.js` を watch している。候補は Next.js 15.1 の公式リリースノート。  
負例（3 にしてはいけない）: タイトルに "Next" とあるが、これは Nextcloud の障害報告。語彙一致の hard negative は 0。

正例（2）: React を常用するフロントエンド開発者に対する Vite のメジャーリリース。隣接だが日常ツール。  
負例（2 にしてはいけない）: 同じ人物に対する PostgreSQL のマイナーリリースで、プロファイルに DB 関心がない。これは 0 または 1。

正例（1）: Kubernetes 運用者に対する一般的な「クラウド障害まとめ」記事。自社サービスの Statuspage ではない。  
負例（1 にしてはいけない）: ユーザーが購読している GitHub Actions Statuspage の進行中インシデント。これは 3。

正例（0）: Python バックエンド開発者に対する iOS ゲームのアプデ。  
負例（0 にしてはいけない）: ユーザーの SBOM に載る `log4j` の新規 CVE。これは 3。

### 8.2 user-importance（0–3）

対象: 関係があるとして、このユーザーが短時間で拾うべき重要度か。relevance が高くても importance は低くてよい。

| 値 | 定義 |
| --- | --- |
| 0 | 見なくても業務に影響しない。 |
| 1 | 知っておくとよいが、今回のセッションで不要。 |
| 2 | 近日の作業や監視に効く。フィード上位に置いてよい。 |
| 3 | 障害・脆弱性・破壊的変更など、見逃すと実害がある。 |

正例（3）: ユーザーの本番依存に対する RCE、または購読 Statuspage の major outage。  
負例（3 にしてはいけない）: 同じ依存の changelog に「ドキュメントの誤字を修正」。relevance は 3 でも importance は 0–1。

正例（2）: 常用ライブラリの非互換マイナーアップ。移行期限は数週間後。  
負例（2 にしてはいけない）: 使っていない隣接製品の料金改定。relevance 1 かつ importance 0–1。

正例（1）: 関心トピックのカンファレンス登壇告知。  
負例（1 にしてはいけない）: 明示的な API 廃止で、ユーザーが呼んでいるエンドポイントが対象。これは 3。

正例（0）: 関係リポジトリの CI バッジ変更のみ。  
負例（0 にしてはいけない）: ユーザーが「important」とフィードバックした系列の続報。少なくとも 2。

### 8.3 semantic equivalence（equivalent / not_equivalent / uncertain）

対象: 2つの Claim / 観測が、同じ事実を述べているか。ユーザー既知度は見ない。既存の `EquivalenceLabel` と一致させる。

| 値 | 定義 |
| --- | --- |
| `equivalent` | 言い換え・語順・表記ゆれだけで、事実が同じ。 |
| `not_equivalent` | 数値、版、日付、否定、主体、状態のいずれかが変わる。 |
| `uncertain` | 正規化しても証拠が足りず、等価とも不等価とも言えない。 |

正例（equivalent）: 「Actions is experiencing degraded performance」と「GitHub Actions の性能が低下している」。同一インシデントの言い換え。  
負例（equivalent にしてはいけない）: 「Actions is down」と「Actions is operating normally」。語彙は近いが事実が逆。`not_equivalent`。

正例（not_equivalent）: 修正版が `1.2.3` から `1.2.4` に変わった。版識別子の変化は常に不等価。  
負例（not_equivalent にしてはいけない）: 「v1.2.3 を公開した」と「version 1.2.3 has been released」。同一版の表記ゆれは `equivalent`。

正例（uncertain）: 一方は「一部リージョンで遅延」、他方は「アジアの利用者から遅延の報告」。範囲が重なるが包含関係が不明。  
負例（uncertain にしてはいけない）: 片方が明示的に「先の発表は誤りで、実際は全リージョン障害」。これは不等価であり、revision は `CORRECTION`。

### 8.4 novelty / revision class

対象: 先行して確定した Claim に対し、新しい観測がどの種の意味変化か。`RevisionType` と同じ語彙を使う。`NON_NOVEL` は通常 FeedItem にしない。

| 値 | 定義 |
| --- | --- |
| `NEW_FACT` | 先行 Claim がない、または別事実の初出。 |
| `DETAIL` | 値・状態は同じで、根拠や付帯情報だけが増える。 |
| `STATE_UPDATE` | 同じスロットの値が時間とともに進む（investigating → identified など）。 |
| `CORRECTION` | 先行事実を撤回・訂正する。 |
| `UNRESOLVED_CONTRADICTION` | ソース間で矛盾が残り、どちらが正しいか未決。 |
| `NON_NOVEL` | 意味的に同じ事実の再掲。 |

正例（NEW_FACT）: その Event で初めて「影響バージョンは 2.1.0 未満」と述べる。  
負例（NEW_FACT にしてはいけない）: 別ソースが同じ影響範囲を言い換えただけ。`NON_NOVEL`。

正例（DETAIL）: 障害の状態は degraded のまま、影響コンポーネント一覧が追記された。  
負例（DETAIL にしてはいけない）: degraded から major outage に変わった。これは `STATE_UPDATE`。

正例（STATE_UPDATE）: Statuspage が investigating から identified に進んだ。  
負例（STATE_UPDATE にしてはいけない）: 「原因は DB」と言っていた発表を「原因は CDN だった」と差し替え。これは `CORRECTION`。

正例（CORRECTION）: 「CVE-2024-0001 は当社製品に影響しない」を翌日「影響する。ただちに更新せよ」へ訂正。  
負例（CORRECTION にしてはいけない）: インシデントが resolved になった通常のライフサイクル。`STATE_UPDATE`。

正例（UNRESOLVED_CONTRADICTION）: 公式 Statuspage は resolved、公式 RSS はまだ identified で、どちらも撤回していない。  
負例（UNRESOLVED_CONTRADICTION にしてはいけない）: 後続観測が「先の resolved は誤報」と明示。裁定できるなら `CORRECTION`。

正例（NON_NOVEL）: 同じ resolved 文面を JSON Feed と Statuspage が再配信。  
負例（NON_NOVEL にしてはいけない）: 同じ文面に見えて否定が1語入っている。`not_equivalent` かつ `STATE_UPDATE` または `CORRECTION`。

### 8.5 knownness / novelty-to-user（already_knew vs new）

対象: このユーザーが、この意味内容をすでに知っているか。配信・表示・既読の機械状態（delivered / displayed / read）のヒントにはしてよいが、機械状態そのものをラベルにしない。semantic equivalence が `equivalent` でも、ユーザーが未読なら `new` であり得る。

| 値 | 定義 |
| --- | --- |
| `already_knew` | プロファイル、明示フィードバック、意味のある閲覧、またはユーザーが「知っている」と示した証拠がある。 |
| `new` | そのユーザーにとって未学習の事実。再配信でも、以前見ていなければ `new`。 |

正例（already_knew）: 同じ Claim を前回セッションで既読にし、今回は別ソースの言い換え。  
負例（already_knew にしてはいけない）: フィードに載ったが viewport に入っていない（delivered のみ）。露出が無意味なら `new` のまま。

正例（new）: ユーザーが follow した直後で、follow 前のベースラインにこの事実がない。  
負例（new にしてはいけない）: ユーザーが onboarding で「この障害は知っている」と明示した。`already_knew`。

訂正は例外的に、既知の誤った事実を更新する。`knownness=already_knew` でも `should_surface=true` になり得る（誤情報の訂正）。

### 8.6 should_surface

対象: このユーザーの今回のフィードに出すべきか。独立判断だが、次を目安にする。

- relevance 0 → 原則 `false`
- `already_knew` かつ revision が `NON_NOVEL` / `DETAIL` → 原則 `false`
- `already_knew` でも `CORRECTION` や未読の `STATE_UPDATE` で実害がある → `true` があり得る
- 曖昧・文脈不足のまま強制的に `true` にしない

正例（true）: 常用依存の新規 CVE（relevance 3, importance 3, knownness new）。  
負例（true にしてはいけない）: 語彙だけ一致する無関係記事（relevance 0）。hard negative は必ず `false`。

正例（false）: 昨日読んだ公式リリースの、別メディアによる全文転載（equivalent / NON_NOVEL / already_knew）。  
負例（false にしてはいけない）: 同じユーザーが読んだ発表の訂正で、影響範囲が広がる。`already_knew` でも `true`。

---

## 9. 作業手順（アノテータ向け）

1. 提示されたプロファイル・事前既知・原文だけを見る。システム予測や他アノテータのラベルは見ない（ブラインド）。
2. 判断不能なら該当ラベル族を `ambiguous` または `insufficient_context` にする。空欄で確定値を埋めない。
3. 事実ラベル（equivalence / revision）を先に付け、その後にユーザーラベル（relevance / importance / knownness / should_surface）を付ける。
4. 短い rationale を残す。後続の裁定と IAA 分析のため。
5. パイロットの代表サブセットは必ず二重ラベルする。不一致は裁定キューへ送る。

## 10. 評価ツール契約

後続データセット（#37 / #55 / #66）は次を守る。

- スキーマは `AnnotationRecord` / `FamilyJudgment` / `AmbiguousFlag` に適合させる。
- マニフェストに `protocol_version` と `provenance` を書く。
- 二重ラベルサブセットを持ち、族ごとの IAA を出せる。
- 裁定は新 `dataset_version` または `adjudication_id` overlay とし、旧版ファイルを上書きしない。
- `split=blind` と `.../blind/` は本番採点の import 対象にしない。
- 未裁定の曖昧件は `filter_unresolved_ambiguous` で除外または別報告する。
