import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config';

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      // CI 用レポート: JSON は集計・注釈、HTML は Pages 公開、JUnit(XML) は他ツール連携用
      reporters: ['default', 'junit', 'json', 'html'],
      // 失敗したテストの行番号を注釈に使う
      includeTaskLocation: true,
      outputFile: {
        junit: 'reports/vitest/junit.xml',
        json: 'reports/vitest/results.json',
        html: 'reports/vitest/html/index.html',
      },
      coverage: {
        provider: 'v8',
        reporter: ['text', 'html', 'json-summary', 'json', 'lcov'],
        reportsDirectory: 'reports/coverage',
        reportOnFailure: true,
        include: ['src/**/*.{ts,tsx}'],
        exclude: ['src/**/*.stories.tsx', 'src/**/*.test.{ts,tsx}', 'src/test/**', 'src/main.tsx', 'src/vite-env.d.ts'],
      },
    },
  }),
);
