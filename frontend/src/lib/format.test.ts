import { describe, expect, it } from 'vitest';
import { formatBytes, formatPercent } from './format';

describe('formatBytes', () => {
  it('picks a readable unit', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
    expect(formatBytes(3 * 1024 * 1024 * 1024)).toBe('3.0 GB');
  });

  it('shows a dash for values that are not sizes', () => {
    expect(formatBytes(-1)).toBe('—');
    expect(formatBytes(Number.NaN)).toBe('—');
  });
});

describe('formatPercent', () => {
  it('appends a percent sign only to real numbers', () => {
    expect(formatPercent(12.345)).toBe('12.35%');
    expect(formatPercent(null)).toBe('—');
  });
});