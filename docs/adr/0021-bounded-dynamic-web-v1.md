# ADR-0021 上限付き動的 Web レンダリング v1

状態: Accepted  
版: `bounded-dynamic-web-v1` / `real-renderer-gate-v2`  
Issue: #64 (Source-08) — **trigger 未達のため defer close。再open 条件は決定成果物を正とする**

## Context

Source-09 の `dynamic_web` は split ごとに JS 必須ケースを必ず含み、実装状態に関係なく `static_coverage_gap` を返す。`js_rendering_implemented=False` は固定で、ここで JS を有効扱いすると release gate 違反になる。

したがって `dynamic_web gap=1.0` は「実在の重要 source を 100% 取りこぼしている」ではなく、静的取得では動的ページを扱えないことを可視化した人工 gap である。これを 0 にするために Playwright を入れるのは評価指標への過適合になる。

一方、generic Web の `#60 → #61 → #62 → #63` の後に、将来の実ブラウザを差し込む境界が無いと、パイプラインへ直接 Playwright をねじ込むことになる。

実ブラウザは HTTP client とは攻撃面が違う。Python の `getaddrinfo` 検査と Chromium の実 DNS は同一ではない（TOCTOU / DNS rebinding）。Service Worker は request interception を迂回しうる。Playwright 公式も untrusted site には別 user / seccomp を推奨する。

## Options

1. 静的取得のまま、レンダ境界も定義しない。
2. 通常 backend に Playwright を直接追加する。
3. **A+:** 契約だけ先に固定し、フラグは OFF。実ブラウザは開始条件を満たしてから isolated service として入れる。

## Decision

方針 3（A+）。

契約（#114）:

- `fetch_web_snapshot` は静的 HTTP のまま。
- `acquire_web_snapshot` / `maybe_render_web_snapshot` が、フラグ + host allowlist + `bounded_js_when_needed` + #61 不足のときだけ `RendererEngine` に入る。
- 本番 default は `NullRenderer`。実ブラウザプロセスは起動しない。
- HTTP と rendered snapshot の provenance を分離する。
- `BULLETFEED_DYNAMIC_WEB_ENABLED` は false のまま。
- Source-09 は静的ギャップ測定のまま。`js_rendering_implemented` を立てない。
- Issue #64 は trigger 未達なら defer close してよい。再open は live 開始条件のみ。
  決定成果物: `backend/tests/gold/source_qualification/v01/renderer_gate_decision.json`

実レンダ開始条件（`real_renderer_gate.py`、live 観測のみ）:

1. 追跡中の primary source が 5 件以上、継続的に JS renderer を必要とする  
   （discovered → static fetch 成功 → #61 では意味内容なし → JS なら取得可能）
2. または #72 important-unknown recall が JS-only source のために 5pt 以上失われる

Source-09 の `dynamic_web` gap と synthetic Gold の JS ケースは条件に使わない。

開始するときの実装は **B2: isolated renderer service**。通常 FastAPI / sync worker へ Playwright を直接足さない。

```text
sync worker → #60 HTTP snapshot → #61
    | insufficient
    v
renderer queue → isolated Chromium container → rendered HTML only
    v
rendered snapshot → #61 → #62 → #63
```

最低限: 別 process/container、non-root + Chromium sandbox + seccomp、egress default deny、実接続 IP の private 拒否、`serviceWorkers: 'block'`、profile / cookie / storage / download なし、不要 API 無効、OS 側の時間・CPU・memory・request 上限、小さい concurrency、Playwright/Chromium pin、renderer 障害で static snapshot を壊さない。

## Consequences

フラグ OFF なら本番 attack surface はほぼ増えない。将来必要性が証明されたとき、既存の `RendererEngine` 境界に isolated service を足せる。#64 は trigger 未達なら defer し、Playwright を入れない。

## Rollback

`BULLETFEED_DYNAMIC_WEB_ENABLED=false`（既定）のままなら静的経路だけが動く。
