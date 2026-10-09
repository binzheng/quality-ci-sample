---
slug: /
sidebar_position: 1
title: ホーム
---

# Quality CI Sample

FE / BE / Docs の 3 プロジェクトで構成されたモノレポのサンプルです。
PR では品質チェックの結果を PR 画面に表示し、`develop` にマージすると品質レポートとこのドキュメントを GitHub Pages に公開します。

## プロジェクト構成

| ディレクトリ | 内容 | 主な技術 |
| --- | --- | --- |
| `fe/` | フロントエンド | React 18 / TypeScript / Vite / Vitest / Storybook |
| `be/` | バックエンド | Java 21 / Spring Boot 3 / Maven |
| `docs/` | ドキュメント (本サイト) | Docusaurus 3 |
| `.github/` | CI/CD | GitHub Actions / Pages |

## 品質チェック一覧

| 対象 | ツール | Pages の枠 | 品質ゲート |
| --- | --- | --- | --- |
| FE | ESLint | `fe/<pkg>/eslint/` | エラーで不合格 |
| FE | Vitest + カバレッジ (v8) | `fe/<pkg>/vitest/` | テスト失敗で不合格 |
| FE | Storybook | `fe/<pkg>/storybook/` | ビルド失敗で不合格 |
| FE | npm audit | `fe/<pkg>/audit/` | 表示のみ |
| FE | SLOCCount (cloc) | `fe/<pkg>/sloc/` | 表示のみ |
| BE | JUnit 5 | `be/tests/` | テスト失敗で不合格 |
| BE | JaCoCo | `be/jacoco/` | 表示のみ |
| BE | Javadoc | `be/javadoc/` | 生成失敗で不合格 |
| BE | Checkstyle | `be/checkstyle/` | `error` 重大度で不合格 |
| BE | SpotBugs | `be/spotbugs/` | High で不合格 |
| Docs | Docusaurus build | `docs/` | ビルド失敗 (リンク切れ含む) で不合格 |
