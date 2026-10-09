// @ts-check
// Pages 向けのビルドでは CI が BASE_URL (例: /quality-ci-sample/docs/) と SITE_URL を渡す
const baseUrl = process.env.BASE_URL || '/';
const siteUrl = process.env.SITE_URL ? new URL(process.env.SITE_URL).origin : 'http://localhost:3000';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Quality CI Sample',
  tagline: 'FE / BE / Docs のモノレポと品質レポートの CI/CD',
  url: siteUrl,
  baseUrl,
  trailingSlash: true,
  // リンク切れは CI で失敗させる
  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'throw',
  i18n: {
    defaultLocale: 'ja',
    locales: ['ja'],
  },
  markdown: {
    // .md は CommonMark、.mdx は MDX として解釈する
    format: 'detect',
    mermaid: true,
  },
  themes: ['@docusaurus/theme-mermaid'],
  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.js',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],
  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      colorMode: {
        respectPrefersColorScheme: true,
      },
      navbar: {
        title: 'Quality CI Sample',
        items: [
          { type: 'docSidebar', sidebarId: 'docs', position: 'left', label: 'ドキュメント' },
          // 品質レポートの索引 (Pages のルート)。docs の外なので pathname:// で書く
          { href: 'pathname:///' + baseUrl.replace(/^\/|docs\/$/g, ''), label: '品質レポート', position: 'right' },
        ],
      },
      footer: {
        style: 'dark',
        copyright: 'Quality CI Sample',
      },
    }),
};

module.exports = config;
