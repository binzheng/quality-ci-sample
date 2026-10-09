# quality-ci-sample

FE / BE / Docs の 3 プロジェクト構成のモノレポに、品質チェックとレポート配布の CI/CD を組み込んだサンプルです。

| ディレクトリ | 内容 | CI で実行するチェック |
| --- | --- | --- |
| `fe/` | React + TypeScript + Vite | ESLint / Vitest (+ coverage) / Storybook / npm audit / SLOCCount (cloc) |
| `be/` | Java 21 + Spring Boot 3 + Maven | JUnit / JaCoCo / Javadoc / Checkstyle / SpotBugs |
| `docs/` | Docusaurus 3 | ビルド (リンク切れで失敗) |

## しくみ

- **PR (develop 宛)**: `ci.yml` が変更のあったプロジェクトだけ検査し、結果を PR 画面に出します
  - チェック一覧の `CI status` (必須チェックはこれ 1 つ)
  - 各ジョブのサマリ (件数・カバレッジ率と develop との差・指摘一覧) と注釈 (失敗テスト・エラーの該当行)
  - PR コメント: 1 チェック 1 行の要約表。各行の「画面」リンクから、テスト結果 (JUnit)・カバレッジ (JaCoCo) などを**それぞれ別の画面**で開ける (push ごとに上書き)
  - 画面はチェックごとの 1 ファイル完結の HTML を圧縮せずに Artifact に保存したもの (`archive: false`)。リンクを開くとブラウザでそのまま表示される
  - 複数ファイルの HTML レポート (JaCoCo・Javadoc 等) は Artifact `pages-<枠>` (zip、14 日)
- **develop へのマージ**: `ci.yml` が Artifact `pages-<枠>` (90 日) を出し、完了後に `pages.yml` が
  **枠ごとに最新の develop の Artifact** を集めて索引画面を生成し、GitHub Pages へ配備します
  (走らなかったジョブの枠も消えません)。週 1 回の定期実行で全ジョブを走らせます。

```
.github/
  scripts/
    report_common.py   # 枠の一覧 (build_catalog)・共通部品
    ci_report.py       # 各ツールの出力 → 枠 / ジョブサマリ / 注釈 / PR コメント / 品質ゲート
    pages_site.py      # 枠ごとの最新 Artifact 取得・サイト組み立て・容量予算・索引画面と site.json
  workflows/
    ci.yml             # PR / develop push / 定期 → 変更検出 → fe・be・docs → CI status → PR コメント
    pages.yml          # develop の CI 完了 → 組み立て → Pages 配備
    fe-quality.yml  be-quality.yml  docs-build.yml   # 再利用ワークフロー
```

## Pages の構成

| パス | 内容 |
| --- | --- |
| `/` | 索引 (ヘッダー・① 概況・② BE・③ FE・④ ドキュメント/推移・⑤ 案内) と `site.json` |
| `/be/{tests,jacoco,javadoc,checkstyle,spotbugs}/` | BE レポート |
| `/fe/<pkg>/{vitest,storybook,eslint,audit,sloc}/` | FE レポート (vitest 配下に `coverage/`) |
| `/docs/` | Docusaurus |
| `/ci-metrics/` | gh-pages ブランチにあれば取り込み |

## GitHub 側の設定

1. **デフォルトブランチを `develop`** にする (`pages.yml` は `workflow_run` のため、デフォルトブランチ上のファイルで動く)
2. **Settings → Pages → Source** を **GitHub Actions** にする
3. (推奨) `develop` のブランチ保護で必須チェックに **`CI status`** を設定する

詳細は Docs の「CI/CD の構成」「PR での確認手順」を参照してください。

## 補足

- **SLOCCount**: 本家 `sloccount` は TypeScript を認識しないため、互換ツールの `cloc` で集計しています。
- **サードパーティ Action を使っていません** (actions/* のみ)。PR コメントと Artifact の取得は `gh` CLI で行います。
- `fe/`・`docs/` で `npm install` を一度実行し、`package-lock.json` をコミットすると CI は `npm ci` で再現性のあるインストールを行います。
