import { describe, expect, it } from 'vitest';
import { formatPrice, truncate } from './format';

describe('formatPrice', () => {
  it('formats USD in en-US', () => {
    expect(formatPrice(1234.5, 'en-US', 'USD')).toBe('$1,234.50');
  });

  it('formats JPY with grouping by default', () => {
    expect(formatPrice(1234)).toContain('1,234');
  });

  it('throws for non-finite values', () => {
    expect(() => formatPrice(Number.NaN)).toThrow(RangeError);
    expect(() => formatPrice(Number.POSITIVE_INFINITY)).toThrow(RangeError);
  });
});

describe('truncate', () => {
  it('returns the text as is when short enough', () => {
    expect(truncate('hello', 5)).toBe('hello');
  });

  it('truncates long text with an ellipsis', () => {
    expect(truncate('hello world', 6)).toBe('hello…');
  });

  it('returns empty string when max is less than 1', () => {
    expect(truncate('hello', 0)).toBe('');
  });
});
