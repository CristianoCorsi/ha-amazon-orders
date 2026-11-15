// Regenerate the demo images shown in the root README (viewport-sized, synthetic data).
// Run against `pnpm dev --port 5173`: `pnpm readme:images`.
import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { screenUrl } from './scenarios.mjs';

const output = fileURLToPath(new URL('../../../docs/images/', import.meta.url));
await mkdir(output, { recursive: true });

// [file name, route, auth state, device, theme]
const shots = [
  ['overview-desktop-light', '/', undefined, 'desktop', 'light'],
  ['overview-desktop-dark', '/', undefined, 'desktop', 'dark'],
  ['deadlines-desktop-light', '/deadlines', undefined, 'desktop', 'light'],
  ['statistics-desktop-dark', '/statistics', undefined, 'desktop', 'dark'],
  ['orders-mobile-light', '/orders', undefined, 'mobile', 'light'],
  ['detail-mobile-dark', '/orders/DEMO-01048', undefined, 'mobile', 'dark'],
  ['signin-mobile-light', '/', 'auth_required', 'mobile', 'light']
];

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || '/usr/sbin/chromium',
  headless: true,
  args: ['--no-sandbox']
});
try {
  for (const [name, route, authState, device, mode] of shots) {
    const context = await browser.newContext({
      viewport: device === 'desktop' ? { width: 1440, height: 900 } : { width: 390, height: 844 },
      deviceScaleFactor: device === 'desktop' ? 1 : 2,
      colorScheme: mode,
      reducedMotion: 'reduce',
      locale: 'en-GB'
    });
    const page = await context.newPage();
    await page.addInitScript((mode) => {
      localStorage.setItem('amazon-orders-language', 'en');
      localStorage.setItem('amazon-orders-theme', mode);
    }, mode);
    await page.goto(screenUrl(route, authState));
    await page.waitForSelector('main h1');
    await page.locator('.skeleton-group').waitFor({ state: 'detached' });
    await page.waitForTimeout(650);
    await page.screenshot({ path: `${output}/${name}.png` });
    console.log(name);
    await context.close();
  }
} finally {
  await browser.close();
}
