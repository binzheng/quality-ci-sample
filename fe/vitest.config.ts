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
      // CI 用レポート: JUnit(XML) は Checks 表示、JSON は集計、HTML は Pages 公開
      reporters: ['default', 'junit', 'json', 'html'],
      outputFile: {
        junit: 'reports/vitest/junit.xml',
        json: 'reports/vitest/results.json',
        html: 'reports/vitest/html/index.html',
      },
      coverage: {
        provider: 'v8',
        reporter: ['text', 'html', 'json-summary', 'lcov'],
        reportsDirectory: 'reports/coverage',
        reportOnFailure: true,
        include: ['src/**/*.{ts,tsx}'],
        exclude: ['src/**/*.stories.tsx', 'src/**/*.test.{ts,tsx}', 'src/test/**', 'src/main.tsx', 'src/vite-env.d.ts'],
      },
    },
  }),
);
