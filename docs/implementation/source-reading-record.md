# ソース読了記録（source reading record）

- 作成日: 2026-08-22
- 対象HEAD: `74fb5d1` (`wogikaze/BulletFeed`, main)
- wiki: `C:\wgkz\BulletFeed-notes`（`wogikaze/BulletFeed-notes` @ clone時点。実装リポジトリには含めない）
- マスタープロンプト: `BULLETFEED_PRODUCTION_MASTER_PROMPT.md`（§0〜§118 + Appendix A〜AA を全読）

## 読了範囲

### 全読

- `AGENTS.md`（wikiスキーマ。実装repoへの直接適用ルールではなく、wiki運用ルール。既知矛盾7件と出典優先順位を確認）
- `wiki/index.md`
- `wiki/syntheses/productization-implementation-plan.md`（Vertical Slice方針・DoD）
- `wiki/syntheses/developer-entry.md`
- `wiki/syntheses/gold-dataset-design.md`（observation単位・bundle split・Track A/B・baseline B0〜B5）
- `wiki/syntheses/semantic-delta-gold-guideline.md`（claim定義・decision order 1-8・label定義）
- `wiki/syntheses/event-identity-clustering-report.md`（4問題分離・over-merge最優先・B0〜B4 ladder）
- `wiki/syntheses/multi-source-conflict-resolution.md`（Assertion/ClaimSlot/AssertionRelation/BeliefSnapshot・時間3分離・retraction別軸）
- `wiki/syntheses/semantic-delta-baseline-experiments.md`（実験計画・metrics）

### 見出し確認済み（実装フェーズ到達時に該当箇所を精読）

- `wiki/syntheses/{source-policy-report,source-ingestion-landscape,semantic-delta-deep-research,bulletfeed-research-map,event-coreference-reading-guide}.md`
- `wiki/comparisons/*.md`, `wiki/concepts/*.md`, `wiki/entities/*.md`
- `raw/sources/**` は裏取りが必要な場合のみ参照

## 現HEAD再観測（Appendix R検証結果）

| Appendix R の指摘 | 現HEADでの状態 |
| --- | --- |
| Kotlin Compose 単一 `:app` | 変わらず |
| DemoData 本番パス | 変わらず（Mock Repository経由） |
| Repository interface不在 | **修正済み**: `BulletFeedRepository` + `MockBulletFeedRepository` 存在 |
| オンボーディング無し | **追加済み**（3ステップ、テーマ5件必須） |
| テスト無し | **追加済み**（`MockBulletFeedRepositoryTest` 4件） |
| SourceモデルにURL無し | 未修正 |
| タイムスタンプが表示文字列 | 未修正 |
| settings編集がno-op | 未修正 |
| GitHub連携がデモトグル | 未修正 |
| backend無し→FastAPI prototype追加済み | SQLite版が存在（新スタックへ移植後に削除） |

## Baselineビルド結果（2026-08-22）

- backend: `ruff check .` PASS / `pytest -q` **7 passed**
- Android: `ktlintCheck` PASS / `lint` PASS / `:app:testDebugUnitTest` PASS
- 環境修正: `JAVA_HOME` はAndroid Studio同梱JBR(Java 25)ではKotlin 2.0.21がバージョン解析に失敗 → Adoptium JDK 17 (`C:\Program Files\Eclipse Adoptium\jdk-17.0.20.8-hotspot`) を使用。`local.properties`(sdk.dir) を作成（gitignore対象）

## 不変条件の確認（wiki⇔マスタープロンプト整合）

- over-mergeよりunder-merge / false NON_NOVEL / false correctionを最重視（曖昧は分離・表示）
- near duplicate ≠ same event ≠ claim novel。embedding/retrievalは候補生成のみ
- valid_time / published_time / observed_at(+effective_at) 分離。表示用「今日」はUI formatter
- assertion append-only、belief snapshotは再生成可能view、retraction≠反対事実
- sourceCountは導出値、独立証拠はdependence groupで補正
- provenance: 表示claim→evidence→observation/snapshot→原URL を切断しない

## 矛盾・要決定事項（ADRで確定）

1. Rating文言（Doc/PDF/repo不一致）→ §3決定: important/not_relevant/read/following。知っていたは将来experimental signal
2. GitHub API pathずれ（contract `/me/integrations/github` vs frontend spec）→ contract側をcanonical
3. データモデル4系統の写像未記載 → ledger正本 + `docs/architecture/model-mapping.md`（Phase 2）
4. 因果抽出 vs 推定影響 → explicit/inferred分離（field/table/provenance単位）
5. 検索API契約未記載 → additive versioned endpoint（ADR-0010）
6. wiki「巨大schemaを作るな」vs マスター「Appendix A全43テーブル」→ 解釈: Vertical Sliceで必要なテーブルから順に実装し、最終的にA全量へ到達する。初期移行はコア（sources/observations/events/claims/state/feed）から段階展開

## 実装開始時の決定事項（ユーザー確認済み）

- LLM/NLI/embedding: v1決定論 + Provider抽象化（キー後付け）
- Git運用: 直接main push可（ブランチ保護無効確認済み）。CI通過を各フェーズで維持
- Windows環境: Makefile + PowerShell script併存、gradleはGit-bash + JDK17
