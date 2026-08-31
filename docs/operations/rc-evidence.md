# RC 証跡の再生成（current SHA）

版: `m7-rc-evidence-v1`  
スクリプト: `backend/scripts/build_rc_evidence_report.py`  
成果物: `backend/tests/gold/release_candidate/v01/rc_evidence_report.json`

このスクリプトは、すでに versioned されている M1–M7 artifact を読み、
current SHA を刻んだ **pre-field** RC bundle を作る。Gold / blind ラベルは読まない。
Mission を PASS に書き換えない。`completion_gate_pass` は常に `false` である。

## 再生成

リポジトリ root で、`GITHUB_SHA` が無いときは `git rev-parse HEAD` を使う。

```text
cd backend
python scripts/build_rc_evidence_report.py
```

CI と同じ検査（SHA が空なら失敗、PASS にはしない）:

```text
python backend/scripts/build_rc_evidence_report.py --check --output "$RUNNER_TEMP/rc-evidence-report.json"
```

M4 / M6 など依存レーンが main に入ったあとは、integrator が current SHA で再実行する。
出力の `status` は `pre_field_release_candidate` のまま残す。

#171 one-shot blind は `oneshot_blind_aggregate.json` を読んで記録する。
現行 holdout は thin のため `aggregate_status=not_scorable` であり、M6 blind PASS とは書かない。
同一 holdout の再調整や拡張はしない。

## やってはいけないこと

- `completion_gate_pass` を `true` に手編集する
- unmet gate や `human_only_or_field_validation` を消して green に見せる
- Gold / blind ラベルを読んで ranker や判定を合わせる
- field 未実施のまま M7 最終判定を PASS にする

field の正は [field-eval-protocol.md](../evaluation/field-eval-protocol.md) の
session telemetry であり、この JSON を field 日記の代わりにしない。
