---
sidebar_position: 4
title: 開発ガイド
---

# 開発ガイド

## ブランチ運用

- `develop` (デフォルトブランチ) から作業ブランチを作り、`develop` 宛に PR を作成します
- `CI status` が ✅ で、レビューが完了したらマージします
- マージ後の develop の CI が終わると、Pages のレポートが更新されます

## ローカルでの実行

### FE (Node.js 22)

```bash
cd fe
npm install
npm run lint        # ESLint
npm run test:ci     # Vitest + カバレッジ (reports/ に出力)
npm run storybook   # Storybook (http://localhost:6006)
npm audit
```

### BE (Java 21 / Maven 3.9)

```bash
cd be
mvn verify                 # JUnit + JaCoCo (target/site/jacoco)
mvn javadoc:javadoc        # Javadoc
mvn checkstyle:check       # Checkstyle (target/checkstyle-result.xml)
mvn spotbugs:check         # SpotBugs (target/spotbugsXml.xml)
mvn spring-boot:run        # http://localhost:8080/api/todos
```

### Docs (Node.js 22)

```bash
cd docs
npm install
npm start                  # http://localhost:3000
npm run build              # リンク切れがあると失敗する
```

## ドキュメントの追加

`docs/docs/` に Markdown を追加すると、サイドバーに自動で並びます (並び順は `sidebar_position`)。
CI は `onBrokenLinks: 'throw'` でビルドするため、リンク切れがあると PR のチェックが失敗します。
