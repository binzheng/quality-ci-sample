# 開発ガイド

## ブランチ運用

- `develop` から作業ブランチを作成し、`develop` 宛に PR を作成します。
- PR の品質ゲートが合格し、レビューが完了したらマージします。
- `develop` へのマージで Pages のレポートが更新されます。

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

### Docs (Python 3.12)

```bash
cd docs
pip install -r requirements.txt
mkdocs serve               # http://127.0.0.1:8000
```

## ドキュメントの追加

`docs/content/` に Markdown を追加し、`docs/mkdocs.yml` の `nav` に登録してください。
CI は `mkdocs build --strict` で実行されるため、リンク切れがあると PR のチェックが失敗します。
