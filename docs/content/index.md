# Quality CI Sample

FE / BE / Docs の 3 プロジェクトで構成されたモノレポのサンプルです。
PR ごとに品質チェックを実行して結果を PR 画面に表示し、`develop` へマージすると品質レポートとこのドキュメントを GitHub Pages に公開します。

<a href="../">📊 最新の品質レポート (ポータル) を開く</a>

## プロジェクト構成

| ディレクトリ | 内容 | 主な技術 |
|---|---|---|
| `fe/` | フロントエンド | React 18 / TypeScript / Vite / Vitest / Storybook |
| `be/` | バックエンド | Java 21 / Spring Boot 3 / Maven |
| `docs/` | ドキュメント (本サイト) | MkDocs Material |
| `.github/` | CI/CD | GitHub Actions / Pages |

## 品質チェック一覧

| 対象 | ツール | 内容 |
|---|---|---|
| FE | ESLint | 静的解析 (エラーがあると不合格) |
| FE | Vitest | 単体テスト + カバレッジ (v8) |
| FE | Storybook | ビルド確認、カタログ公開 |
| FE | npm audit | 依存パッケージの脆弱性警告 |
| FE | SLOCCount (cloc) | ソース行数の集計 |
| BE | JUnit 5 | 単体テスト / API テスト |
| BE | JaCoCo | カバレッジ |
| BE | Javadoc | API ドキュメント生成と警告集計 |
| BE | Checkstyle | コーディング規約 |
| BE | SpotBugs | バグパターン検出 |
