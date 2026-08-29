# ADR-0012 意味のあるビューポート露出方針 v1

状態: Accepted  
版: `viewport-exposure-v1`  
Issue: #51 (Known-03)

## Context

カードが高速スクロール中に一瞬 viewport に入っても、ユーザーがその Claim を知ったとは言えない。#49 の知識証跡は `KIND_DISPLAYED` を medium confidence の閲覧証拠として扱う。任意ピクセルの露出でこれを書くと knownness が過大になる。

#52 の follow baseline と、不確実な証拠での hard-hide はこの ADR の対象外。

## Options

1. クライアントが「見えた」と判断した delivery をすべて `displayed` にする（現行）。
2. 最短滞在時間と可視割合の両方を満たした露出だけを `displayed` にする。
3. 詳細を開くまで `displayed` にしない。

## Decision

方針 2。パラメータは版付きで固定する。

| パラメータ | 値 | 意味 |
| --- | --- | --- |
| `POLICY_VERSION` | `viewport-exposure-v1` | 監査用。再計算可能な版 |
| `MIN_DWELL_MS` | `1000` | 閾値以上の可視割合を連続して満たした最短時間 |
| `MIN_VISIBLE_RATIO` | `0.50` | カード高さに対する viewport 交差割合 |

判定:

- `detail_opened=true`（Event detail を開いた）→ 意味のある表示。dwell / ratio が低くてもよい。
- `dwell_ms` と `visible_ratio` の両方が欠ける → **displayed（既存クライアント互換）**。
- どちらかが送られた場合、送られた値はそれぞれの閾値を満たす必要がある。短すぎる滞在やごく一部だけの交差は `displayed` にしない。
- `GET /feed` は従来どおり `delivered` だけを書く。delivered ≠ displayed。
- 不確実な displayed は hide しない（#49 の `probably_known` → demote）。

Android は layout 変化時に可視割合を計算し、閾値を超えている間だけ dwell を積む。満たした delivery だけを `POST /v1/feed/exposures` に `dwellMs` と `visibleRatio` 付きで送る。高頻度の生スクロール座標は送らない。再 compose / 回転で同じ tracker が残っていれば dwell をリセットしない。POST 失敗は recorded 扱いにせず再送できる。

Backend は同じ関数で再判定する。政策を満たさない item は `exposures` にも `KIND_DISPLAYED` にも書かない。同じ `deliveryId` の後続の意味のある POST が通る。受理した行に `dwell_ms` / `visible_ratio` / `policy_version` / `detail_opened` を残し、なぜ数えたかを監査できる。

## Consequences

- 既存クライアント（メトリクスなし）は従来どおり displayed になる。
- 新クライアントの高速スクロールは知識証跡にならない。
- 閾値変更は新しい `POLICY_VERSION` とする。

## Evidence

- `backend/app/services/viewport_exposure.py`
- `app/src/main/java/com/bulletfeed/app/domain/ViewportExposure.kt`
- `backend/tests/test_viewport_exposure.py`
- `app/src/test/java/com/bulletfeed/app/ViewportExposureTest.kt`

## Rollback

`is_meaningful_display` を常に true に戻し、Android を即時 POST に戻せば v1 以前の契約になる。監査列は nullable のまま残してよい。
