import { describe, it, expect } from 'vitest';
import { resolveLocale, money, date, daysLeft } from './i18n';
import { extractTheme, contrastRatio } from './theme';
describe('locale and presentation', () => {
  it('prioritizes a supported override, HA, browser, then English', () => {
    expect(resolveLocale('it', 'en', 'en-US')).toBe('it');
    expect(resolveLocale(null, 'it-IT', 'en-US')).toBe('it');
    expect(resolveLocale(null, 'fr', 'it-IT')).toBe('it');
    expect(resolveLocale(null, null, 'fr')).toBe('en');
  });
  it('formats euros without converting their amount', () => {
    expect(money(1234.5, 'it')).toContain('1.234,50');
    expect(money(null, 'en')).toBe('Not available');
  });
  it('formats ISO dates as local calendar dates and counts civil days', () => {
    expect(date('2026-11-15', 'en')).toBe('15 Nov 2026');
    expect(daysLeft('2026-11-17', '2026-11-15')).toBe(2);
    expect(daysLeft(null)).toBeNull();
  });
});
describe('HA theme extraction', () => {
  it('preserves HA color but derives readable labels and button text', () => {
    const theme = extractTheme({ '--primary-color': '#03a9f4' }, false, false);
    expect(theme.tokens['--primary']).toBe('#03a9f4');
    expect(contrastRatio(theme.tokens['--primary-ink'], '#e0f0f8')).toBeGreaterThan(4.5);
    expect(contrastRatio(theme.tokens['--on-primary'], '#03a9f4')).toBeGreaterThan(4.5);
  });
  it('uses HA tokens and explicit dark-mode state with safe fallbacks', () => {
    const theme = extractTheme(
      { '--primary-color': ' #03a9f4 ', '--card-background-color': '#202020' },
      true,
      false
    );
    expect(theme.dark).toBe(true);
    expect(theme.tokens['--primary']).toBe('#03a9f4');
    expect(theme.tokens['--surface']).toBe('#202020');
    expect(theme.tokens['--text']).toBeTruthy();
  });
  it('uses OS preference when parent is absent and rejects empty values', () => {
    const theme = extractTheme({ '--primary-color': ' ' }, undefined, true);
    expect(theme.dark).toBe(true);
    expect(theme.tokens['--primary']).not.toBe('');
  });
});
