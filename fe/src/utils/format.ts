/**
 * 数値を通貨表記に整形する。
 * @param value 金額
 * @param locale ロケール (既定: ja-JP)
 * @param currency 通貨コード (既定: JPY)
 */
export function formatPrice(value: number, locale = 'ja-JP', currency = 'JPY'): string {
  if (!Number.isFinite(value)) {
    throw new RangeError('value must be a finite number');
  }
  return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value);
}

/**
 * 文字列を最大長で切り詰め、末尾に省略記号を付ける。
 * @param text 対象文字列
 * @param max 最大文字数 (省略記号を含む)
 */
export function truncate(text: string, max: number): string {
  if (max < 1) {
    return '';
  }
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

/**
 * 件数を「n 件」形式にする。
 * @param count 件数
 */
export function formatCount(count: number): string {
  return `${Math.max(0, Math.trunc(count))} 件`;
}
