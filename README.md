# quality-ci-sample

FE / BE / Docs の 3 プロジェクト構成のモノレポに、品質チェックの CI/CD を組み込んだサンプルです。

| ディレクトリ | 内容 | CI で実行するチェック |
|---|---|---|
| `fe/` | React + TypeScript + Vite | ESLint / Vitest (+ coverage) / Storybook / npm audit / SLOCCount (cloc) |
| `be/` | Java 21 + Spring Boot 3 + Maven | JUnit / JaCoCo / Javadoc / Checkstyle / SpotBugs |
| `docs/` | MkDocs Material | `mkdocs build --strict` |

- **PR 作成・更新時** (`pr-quality.yml`): すべてのチェックを実行し、結果を **PR コメント** (毎回上書き)・**Checks タブ** (テスト結果)・ジョブ Summary に表示します。HTML レポートは Artifacts に保存されます。
- **`develop` へのマージ時** (`pages.yml`): 同じチェックを実行し、レポートと Docs を **GitHub Pages** に公開します。

```
.github/
  scripts/summarize.py      # レポート集計 (PR コメント / HTML / Pages ポータル / 品質ゲート)
  workflows/
    pr-quality.yml          # PR → チェック → PR コメント
    pages.yml               # develop push → チェック → Pages デプロイ
    fe-quality.yml          # 再利用: FE チェック
    be-quality.yml          # 再利用: BE チェック
    docs-build.yml          # 再利用: Docs ビルド
fe/  be/  docs/
```

## GitHub 側の初期設定

1. リポジトリを作成して push し、`develop` ブランチも push します。
   ```bash
   git remote add origin https://github.com/<owner>/quality-ci-sample.git
   git push -u origin main develop
   ```
2. **Settings → Pages → Build and deployment → Source** を **GitHub Actions** にします。
3. **Settings → Environments → github-pages → Deployment branches and tags** に `develop` を追加します。
   (既定ではデフォルトブランチしかデプロイできないため。`develop` をデフォルトブランチにする場合は不要)
4. (推奨) **Settings → Branches** で `develop` の保護ルールを作成し、必須チェックに
   `fe / FE (...)`、`be / BE (...)`、`docs / Docs (MkDocs)` を設定します。
5. (任意) `fe/` で `npm install` を一度実行し、生成された `package-lock.json` をコミットすると CI が `npm ci` で再現性のあるインストールを行います。

## Pages の構成

| パス | 内容 |
|---|---|
| `/` | ポータル (品質ゲートの合否と全レポートへのリンク) |
| `/fe/` | ESLint・Vitest・Coverage・Storybook・npm audit・SLOC |
| `/be/` | JUnit・JaCoCo・Javadoc・Checkstyle・SpotBugs |
| `/docs/` | MkDocs ドキュメント |

## 補足

- **SLOCCount**: 本家 `sloccount` は TypeScript/TSX を認識しないため、互換ツールの `cloc` で集計しています (Jenkins SLOCCount プラグインも cloc の出力を使う方式が一般的です)。
- **品質ゲート**: ESLint エラー、テスト失敗、Storybook ビルド失敗、Checkstyle `error`、SpotBugs High、Javadoc/MkDocs 生成失敗で不合格になります。条件は `.github/scripts/summarize.py` で調整できます。
- フォークからの PR では `GITHUB_TOKEN` が読み取り専用になるため、PR コメントと Checks の投稿はスキップされます (失敗します)。

詳細は `docs/` (Pages の `/docs/`) を参照してください。
