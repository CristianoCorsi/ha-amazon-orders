export const tokenMap: Record<string, string> = {
  '--primary-color': '--primary',
  '--accent-color': '--accent',
  '--primary-background-color': '--background',
  '--secondary-background-color': '--surface-muted',
  '--card-background-color': '--surface',
  '--primary-text-color': '--text',
  '--secondary-text-color': '--text-muted',
  '--divider-color': '--border',
  '--error-color': '--danger',
  '--warning-color': '--warning',
  '--success-color': '--success'
};
const light: Record<string, string> = {
  '--primary': '#087989',
  '--accent': '#087989',
  '--background': '#f3f7f8',
  '--surface-muted': '#eaf0f2',
  '--surface': '#fcfefe',
  '--text': '#172c35',
  '--text-muted': '#516973',
  '--border': '#dbe5e9',
  '--danger': '#b53936',
  '--warning': '#94610c',
  '--success': '#267351'
};
const dark: Record<string, string> = {
  '--primary': '#80d2df',
  '--accent': '#80d2df',
  '--background': '#101b21',
  '--surface-muted': '#203038',
  '--surface': '#19272f',
  '--text': '#e0ecf0',
  '--text-muted': '#a8bcc5',
  '--border': '#32454e',
  '--danger': '#ffb4ab',
  '--warning': '#edc176',
  '--success': '#95d8b3'
};
function rgb(color: string): number[] | null {
  const hex = color?.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i)?.[1];
  if (hex) {
    const full =
      hex.length === 3
        ? hex
            .split('')
            .map((c) => c + c)
            .join('')
        : hex;
    return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
  }
  const values = color?.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i);
  return values ? values.slice(1, 4).map(Number) : null;
}
function luminance(color: string): number {
  const channels = (rgb(color) ?? [0, 0, 0]).map((v) => {
    const c = v / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}
export function contrastRatio(a: string, b: string): number {
  const x = luminance(a),
    y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}
function mix(a: string, b: string, weight: number): string {
  const x = rgb(a),
    y = rgb(b);
  if (!x || !y) return b;
  return (
    '#' +
    x
      .map((c, i) =>
        Math.round(c * weight + y[i] * (1 - weight))
          .toString(16)
          .padStart(2, '0')
      )
      .join('')
  );
}
function readableInk(color: string, surface: string, text: string): string {
  const tonal = mix(color, surface, 0.12);
  let ink = color;
  for (let weight = 1; weight >= 0; weight -= 0.05) {
    ink = mix(color, text, weight);
    if (contrastRatio(ink, tonal) >= 5.2 && contrastRatio(ink, surface) >= 5.2) return ink;
  }
  return text;
}
export function extractTheme(
  values: Record<string, string>,
  haDark: boolean | undefined,
  prefersDark: boolean
) {
  const isDark = haDark ?? prefersDark;
  const tokens = { ...(isDark ? dark : light) };
  for (const [ha, local] of Object.entries(tokenMap))
    if (values[ha]?.trim()) tokens[local] = values[ha].trim();
  for (const name of ['primary', 'danger', 'warning', 'success'])
    tokens[`--${name}-ink`] = readableInk(
      tokens[`--${name}`],
      tokens['--surface'],
      tokens['--text']
    );
  tokens['--on-primary'] =
    contrastRatio('#101b21', tokens['--primary']) > contrastRatio('#fcfefe', tokens['--primary'])
      ? '#101b21'
      : '#fcfefe';
  return { dark: isDark, tokens };
}
export function observeTheme(getOverride: () => string = () => 'auto'): () => void {
  const preference = matchMedia('(prefers-color-scheme: dark)');
  let observer: MutationObserver | undefined;
  function apply() {
    let values: Record<string, string> = {};
    let haDark: boolean | undefined;
    try {
      if (window.parent !== window) {
        const parent = window.parent.document;
        const ha = parent.querySelector('home-assistant') as HTMLElement & {
          hass?: { themes?: { darkMode?: boolean } };
        };
        const rootStyle = window.parent.getComputedStyle(parent.documentElement);
        const haStyle = ha ? window.parent.getComputedStyle(ha) : null;
        for (const key of Object.keys(tokenMap))
          values[key] = haStyle?.getPropertyValue(key).trim() || rootStyle.getPropertyValue(key);
        haDark = ha?.hass?.themes?.darkMode;
      }
    } catch {
      /* ingress may be opened outside HA */
    }
    const override = getOverride();
    if (override !== 'auto') {
      values = {};
      haDark = override === 'dark';
    }
    const theme = extractTheme(values, haDark, preference.matches);
    const root = document.documentElement;
    root.dataset.theme = theme.dark ? 'dark' : 'light';
    root.style.colorScheme = theme.dark ? 'dark' : 'light';
    for (const [key, value] of Object.entries(theme.tokens)) root.style.setProperty(key, value);
  }
  apply();
  try {
    if (window.parent !== window) {
      observer = new MutationObserver(apply);
      observer.observe(window.parent.document.documentElement, {
        attributes: true,
        subtree: true,
        attributeFilter: ['style', 'class', 'dark-mode']
      });
    }
  } catch {
    /* cross-origin */
  }
  preference.addEventListener('change', apply);
  window.addEventListener('amazon-theme-change', apply);
  const timer = window.setInterval(apply, 2000);
  return () => {
    observer?.disconnect();
    clearInterval(timer);
    preference.removeEventListener('change', apply);
    window.removeEventListener('amazon-theme-change', apply);
  };
}
