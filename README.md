# moo-margin-tracker

日本株の **信用残・信用評価損益率・信用倍率**（二市場合計）を週次で自動更新し、
日経平均と重ねて表示するウィジェットをロリポップへ自動デプロイするリポジトリ。

```
moo-margin-tracker/
├── README.md
├── requirements.txt
├── scripts/
│   └── update_margin.py        # sinyou.php を取得→最新1週を margin-data.json に追記
├── .github/workflows/
│   └── update.yml              # 毎週 木08:00 JST 実行 + 手動実行
└── public/
    ├── margin-balance.html     # ウィジェット（margin-data.json を読む / 無ければ内蔵シード）
    └── margin-data.json        # 全履歴シード（2014-08〜2026-06 の599週）
```

## 仕組み（完全自動）

1. GitHub Actions が週1回 `update_margin.py` を実行
2. `update_margin.py` が3段構えでデータ取得（**F12不要・全自動**）:
   - A: `sinyou.php` の表を直接パース（サーバー描画になった場合の保険）
   - B: ページが参照する同一ドメインの .js/.php を自動巡回し、
        「日付＋数値10列」の信用残データ配列を発見して抽出 ←通常はこれが動く
   - C: 失敗時は候補URL一覧をログ出力（貼ってもらえれば即調整）
   最新1週を単位変換（百万株→千株 / 億円→百万円）して追記
3. 変更があれば commit
4. `public/` を **FTP-Deploy-Action** でロリポップの heatmaps フォルダへアップロード
5. ウィジェット（固定ページに iframe 埋め込み）が `margin-data.json` を読んで描画
   - 日経平均は別途、サイト上の `stock-proxy.php` 経由で Yahoo Finance(^N225) から取得

> **注**: sinyou.php の表はJavaScript描画でHTML自体は空（確認済み）。そのため
> Strategy B がページの参照スクリプトを巡回してデータファイルを自動発見する。
> 一度発見されたらログにURLが出るので、Secrets `MARGIN_DATA_URL` に設定すると
> 次回以降は巡回を省略して高速・安定化できる（任意）。

## セットアップ

### GitHub Secrets（4個・すべてFTP系）

| Name | 用途 |
| --- | --- |
| `LOLIPOP_FTP_HOST` | 既存トラッカーと同じFTPホスト |
| `LOLIPOP_FTP_USER` | 同 ユーザー |
| `LOLIPOP_FTP_PASSWORD` | 同 パスワード |
| `LOLIPOP_FTP_HEATMAP_PATH` | アップ先。例 `/wp-content/uploads/heatmaps/` |
| `MARGIN_DATA_URL`（任意） | 自動発見されたデータURLを固定したい時のみ |

FTP系3つは既存リポジトリの値を流用可。APIキー等は不要。

### 初回の動作確認

1. Actions タブ → **Margin Balance Weekly Update** → **Run workflow**
2. ログを確認:
   - `[i] discovered data file: ...` + `[i] latest: 2026-06-XX ...` → 成功。
     表示されたURLを Secrets `MARGIN_DATA_URL` に入れておくと以後安定（任意）。
   - `[!] データを自動発見できませんでした` + 候補URL一覧 → その部分のログを
     AIに貼れば、1回でマッピングを確定できる。
3. 成功後、ロリポップ上の `margin-data.json` 更新を確認
   → 固定ページを **シークレットウィンドウ**で開いて反映確認（WP Fastest Cache のキャッシュ削除も）

### 手動追記（保険）

スクレイプが一時的に失敗しても、「Run workflow」→ `manual_row` に1週分のJSONを貼れば追記できる:

```json
{"d":"2026-06-12","sN":440000,"sA":890000,"bN":3930000,"bA":6700000,"e":-0.55}
```
（単位は 千株/百万円。sC/bC/r は省略可＝前週から自動計算）

## スケジュール

`cron: '0 23 * * 3'` = 毎週 **水23:00 UTC = 木08:00 JST**。
二市場の信用評価損益率は週半ば（水曜頃）に出揃うため、その後に取得する設計。ズレたら cron を調整。

## FTP衝突対策（重要）

`state-name` は **`.ftp-deploy-margin.json`**（固有）。「FTP衝突対策」メモの命名表に追記：

| テーマ | state-name | 出力JSON | 出力HTML |
| --- | --- | --- | --- |
| 信用残 | `.ftp-deploy-margin.json` | `margin-data.json` | `margin-balance.html` |

`local-dir: ./public/` には**このテーマのファイルだけ**を置く。

## データの注意

- 出典の単位は 株数=百万株・金額=億円。スクリプトが `×1000`(千株)/`×100`(百万円) に変換して保存。
- 絶対値は出典の解像度依存。直近45週はスクショ由来の精密値、それ以前は丸め。
  変化率・信用倍率・評価損益率・チャート形状は単位に依存せず正確。
- ウィジェットは `margin-data.json` が取れない環境（プレビュー等）では内蔵シード(599週)で表示。
