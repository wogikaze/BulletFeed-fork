# フロントエンド stacked PR

このブランチは、親バックエンドPR #1（`completion-pr`）を土台にフロントエンド実装を進めるためのstacked PRです。

## 前提

- baseは `completion-pr` とする。
- PR #1が `main` にマージされるまでは、フロントエンドPRを `main` へ直接向けない。
- バックエンドAPIの契約をフロントエンド側で推測して補完しない。
- API契約の変更が必要な場合は、バックエンド側の変更を先に明示的な差分として積む。

## 実装済み

- Remote Repositoryを既定化し、session、Feed、EventDetail、profile、topics、GitHub、security、notificationsを実APIへ接続。
- Feedはbackendのrelation filterとcursor paginationを利用し、重要 / 不要 / 既読 / フォローを明示操作に統一。
- FeedItemの意味のある画面露出（dwell + 可視割合、または detail を開く）をdeliveryId単位で `/v1/feed/exposures` へ記録。一瞬の交差は送らない。
- 空Feedからテーマ管理またはGitHub連携へ遷移可能。
- Topicsはcatalog検索、technology / service / company追加、priority変更、order変更、削除を実APIへ接続。
- Settingsのprofile編集を実APIへ接続。
- GitHub OAuth、repository pagination/選択、権限喪失、security alerts、notificationsを実データで扱う。
- loading / empty / error / pagination、401 / 403 / 404を画面状態として扱う。
- API contract helperとpagination mergeにunit testを追加。

## 実装方針

- APIレスポンス型、nullable、pagination、認証、error responseを現在のバックエンド契約に合わせる。
- private repositoryの権限失効や認証切れを含む境界条件をUIで安全に扱う。
- importance、relation、semantic deltaはバックエンドをsource of truthとし、Android側で再計算しない。
- UI変更には対応するテストを追加する。
- Android qualityをgreenに保つ。

## stackの扱い

PR #1が `main` にマージされた後、このPRのbaseを `main` へ変更またはrebaseする。それまでは `completion-pr` の上でフロントエンド差分のみを積む。

最終レビュー対象は、通常のAndroid quality・Backend quality・Backend security gateがすべてgreenであるheadとする。
