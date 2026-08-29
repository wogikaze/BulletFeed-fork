# ADR-0021 上限付き動的 Web レンダリング v1

状態: Accepted  
版: `bounded-dynamic-web-v1`  
Issue: #64 (Source-08)

## Context

Source-09 の `dynamic_web` ケースは静的 HTTP だけでは本文を取れない（pilot/blind とも `static_coverage_gap_rate = 1.0`）。一方でブラウザ実行は SSRF・Cookie・供給鎖のリスクがある。

## Options

1. 静的取得のまま JS 必須ページを捨てる。
2. 本番デフォルトで Playwright を起動する。
3. 静的取得を既定にし、方針＋必要性＋ホスト allowlist が揃ったときだけ上限付きレンダ経路を開く。実ブラウザは注入し、未設定なら fail-closed。

## Decision

方針 3。

- `fetch_web_snapshot` は静的 HTTP のまま。
- `maybe_render_web_snapshot` が #61 正規化不足のときだけレンダする。
- レンダスナップショットは `acquisition_mode=bounded_js_render` と `parent_http_snapshot_id` を持ち、HTTP 応答と区別する。
- 待ち条件は `domcontentloaded` / `networkidle` / `selector`。任意 sleep は使わない。
- Cookie / ログイン / 私的ブラウジングは対象外。
- Android WebView の JavaScript は有効化しない。
- Source-09 ベンチは静的ギャップ測定のまま。`js_rendering_implemented` を立てない。

## Consequences

JS 必須の公式ページを、静的成功ページを無駄にレンダせず取得できる。本番で実ブラウザを載せるかは別のセキュリティ判断。

## Rollback

`BULLETFEED_DYNAMIC_WEB_ENABLED=false`（既定）に戻せば静的経路だけになる。
