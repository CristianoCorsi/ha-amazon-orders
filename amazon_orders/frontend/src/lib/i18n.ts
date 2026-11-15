export type Locale = 'en' | 'it';
export function resolveLocale(
  override?: string | null,
  ha?: string | null,
  browser?: string | null
): Locale {
  for (const value of [override, ha, browser]) {
    const code = value?.toLowerCase().split('-')[0];
    if (code === 'en' || code === 'it') return code;
  }
  return 'en';
}
export function money(value: number | null | undefined, locale: Locale, currency = 'EUR'): string {
  return value == null
    ? locale === 'it'
      ? 'Non disponibile'
      : 'Not available'
    : new Intl.NumberFormat(locale === 'it' ? 'it-IT' : 'en-IE', {
        style: 'currency',
        currency,
        useGrouping: true
      }).format(value);
}
export function date(value: string | null | undefined, locale: Locale): string {
  if (!value) return locale === 'it' ? 'Sconosciuta' : 'Unknown';
  const parsed = new Date(value.slice(0, 10) + 'T12:00:00');
  if (isNaN(parsed.getTime())) return locale === 'it' ? 'Sconosciuta' : 'Unknown';
  return new Intl.DateTimeFormat(locale === 'it' ? 'it-IT' : 'en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric'
  }).format(parsed);
}
export function daysLeft(
  value: string | null | undefined,
  today = new Date().toLocaleDateString('en-CA')
): number | null {
  if (!value) return null;
  const days =
    (Date.parse(value.slice(0, 10) + 'T00:00:00Z') - Date.parse(today + 'T00:00:00Z')) / 86400000;
  return Number.isFinite(days) ? Math.round(days) : null;
}
export function initialLocale(): Locale {
  let ha: string | undefined;
  try {
    ha = (
      window.parent.document.querySelector('home-assistant') as HTMLElement & {
        hass?: { language?: string };
      }
    )?.hass?.language;
  } catch {
    /* cross-origin standalone */
  }
  let override: string | null = null;
  try {
    override = localStorage.getItem('amazon-orders-language');
  } catch {
    /* private browser */
  }
  return resolveLocale(override, ha, navigator.language);
}
