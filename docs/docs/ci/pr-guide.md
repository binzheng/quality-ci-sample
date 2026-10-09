---
sidebar_position: 2
title: PR での確認手順
---

# PR・ブランチの CI 結果の確認手順

## 前提: ブランチへの push だけでは CI は走らない

CI の契機は **develop 向けの PR** と **develop への push** です。作業ブランチに push しただけでは動きません。

- ブランチの結果を見たいときは **PR を作ります**。レビュー前なら **Draft PR** にします
- PR に push するたびに CI が走り直し、同じ PR の古い実行は取り消されます

## PR 画面で見られるもの

| 内容 | develop (Pages) | PR 画面 |
| --- | --- | --- |
| ジョブごとの合否 | 索引の「状態」 | チェック一覧。まとめは `CI status` |
| 失敗の原因 | 各レポート | 失敗したテスト・ESLint エラー等を**注釈**で該当行に表示 |
| テスト件数・失敗数・カバレッジ率 | 概況カード・各行 | 各ジョブの**サマリ**と **PR コメント** (develop との差つき) |
| HTML レポート | Pages で直接開く | Artifact `pages-*` (zip、14 日) をダウンロード |

合否・件数・率・失敗箇所は PR 画面だけで判断できます。HTML レポートそのものは Pages と同じものを Artifact に残しますが、ダウンロードして手元で開く必要があります。

:::note PR コメントについて
PR コメントは補助です。フォークや Dependabot の PR では書き込めないため、正はチェック一覧とジョブのサマリです。
:::

## 確認手順 (画面)

1. PR の下部のチェック一覧 (または「Checks」タブ) で `CI status` が ✅ かを見る。❌ のときは失敗したジョブの「Details」を開く
2. 失敗したテストや ESLint のエラーは、「Files changed」タブの該当行とジョブの Annotations に出る
3. 実行の「Summary」を開くと、ジョブごとのサマリ (件数・カバレッジ・指摘一覧) が並ぶ
4. 同じ画面の下部「Artifacts」から、見たいレポート (`pages-<枠>`) の zip をダウンロードする
5. zip を展開して開く

| レポート | 開き方 |
| --- | --- |
| JaCoCo / Javadoc / FE カバレッジ / Checkstyle 等の一覧 | 展開した `index.html` を直接開ける |
| Vitest の HTML レポート / Storybook / Docs | `fetch` を使うため、`npx http-server <展開先>` などでローカル配信して開く |

## 確認手順 (gh コマンド)

```bash
# PR のチェック一覧と合否
gh pr checks <PR番号>

# PR の最新の CI 実行を特定して見る
gh run list --workflow ci.yml --branch <ブランチ名> --limit 1
gh run view <実行ID>

# レポートをダウンロードして開く
gh run download <実行ID> -n pages-fe-demo-fe-vitest -D ./tmp/vitest
npx http-server ./tmp/vitest
```
