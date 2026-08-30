# M6 measured remediation input

M2 の pilot/dev production-scoring report から、重要な unknown が top-10 に入らなかった
ranking-stage failure を選定する。選定は `python backend/scripts/select_m6_top3_clusters.py
--output backend/tests/gold/m6/v01/top3_selection.json` で再実行できる。

## Selection rule

`important_unknown_missed` の persona-family cluster を失敗数の降順で並べ、20件以上の
representative case を持つ上位3群を選ぶ。同数の場合は persona-family 名で安定ソートする。
選定時の label は `AI-silver` であり、Human Gold ではない。blind path は production-scoring
loader と selection script のどちらからも構築しない。

Current selection:

- `package_release_manager`: 1,064 important-unknown ranking misses
- `rust_compiler_contributor`: 516 important-unknown ranking misses
- `javascript_tooling_maintainer`: 420 important-unknown ranking misses

各群について20件を `top3_selection.json` に保存し、profile/event/source family/language、
ranking position、rationale、earliest stage (`ranking`) を保持する。

## Boundary

この選定は M6 の dev/adversarial remediation input であり、production algorithm を変更した
証拠ではない。今回の評価で attribution できるのは ranking stage の miss だけで、acquisition、
projection、evidence の earliest-stage attribution は full journey trace で別途確認する。
blind holdout への tuning や one-shot blind evaluation は、この入力選定だけでは実行しない。
