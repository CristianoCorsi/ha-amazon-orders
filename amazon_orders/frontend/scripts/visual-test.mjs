// Run against `pnpm dev --port 5173`. All fixtures are synthetic.
import { chromium } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { screens, screenUrl } from './scenarios.mjs';
const output = fileURLToPath(new URL('../../../docs/screenshots/', import.meta.url));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: '/usr/sbin/chromium',
  headless: true,
  args: ['--no-sandbox']
});
const errors = [];
const results = [];
try {
  for (const language of ['en', 'it'])
    for (const mode of ['light', 'dark'])
      for (const device of ['desktop', 'mobile']) {
        const context = await browser.newContext({
          viewport:
            device === 'desktop' ? { width: 1440, height: 1080 } : { width: 390, height: 844 },
          colorScheme: mode,
          reducedMotion: 'reduce',
          locale: 'en-GB'
        });
        const page = await context.newPage();
        page.on('pageerror', (e) => errors.push(e.message));
        await page.addInitScript(
          ({ mode, language }) => {
            localStorage.setItem('amazon-orders-language', language);
            localStorage.setItem('amazon-orders-theme', mode);
          },
          { mode, language }
        );
        for (const [name, route, authState] of screens) {
          await page.goto(screenUrl(route, authState));
          await page.waitForSelector('main h1');
          await page.waitForTimeout(650);
          await page.locator('.skeleton-group').waitFor({ state: 'detached' });
          await page.screenshot({
            path: `${output}/${name}-${device}-${mode}${language === 'it' ? '-it' : ''}.png`,
            fullPage: true
          });
          const size = await page.evaluate(() => ({
            width: innerWidth,
            scroll: document.documentElement.scrollWidth
          }));
          assert.ok(
            size.scroll <= size.width,
            `${name}/${device}/${mode}: horizontal overflow ${JSON.stringify(size)}`
          );
          assert.equal(
            await page.locator('main .empty-state[role="alert"]').count(),
            0,
            `${name} loaded without API errors`
          );
          results.push(`${name}-${device}-${mode}${language === 'it' ? '-it' : ''}`);
        }
        await context.close();
      }
  // Exercise behavior, not just screenshots.
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    locale: 'en-GB'
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('http://127.0.0.1:5173/#/orders');
  await page.getByRole('searchbox').fill('Luma');
  await page.waitForTimeout(700);
  assert.equal(await page.locator('.order-list .order-row').count(), 9);
  await page.getByRole('searchbox').fill('no-such-synthetic-product');
  await page.waitForTimeout(700);
  await page.getByRole('heading', { name: 'No orders here, yet' }).waitFor();
  await page.goto('http://127.0.0.1:5173/#/orders/DEMO-01048');
  await page.getByLabel('Your note', { exact: true }).fill('Synthetic test annotation');
  await page.getByRole('button', { name: 'To return', exact: true }).click();
  await page.getByLabel('Warranty duration', { exact: true }).selectOption('months');
  await page.getByLabel('Number of months').fill('36');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await page.getByText('Saved locally', { exact: true }).waitFor();
  // A hash navigation does not reload the mock process.
  await page.evaluate(() => (location.hash = '/orders'));
  await page.waitForTimeout(650);
  await page.evaluate(() => (location.hash = '/orders/DEMO-01048'));
  await page.waitForTimeout(500);
  assert.equal(
    await page.getByLabel('Your note', { exact: true }).inputValue(),
    'Synthetic test annotation'
  );
  assert.equal(await page.getByLabel('Number of months').inputValue(), '36');
  await page.evaluate(() => (location.hash = '/settings'));
  await page.waitForTimeout(500);
  await page.getByRole('button', { name: 'Pause backfill', exact: true }).click();
  await page.getByRole('button', { name: 'Resume backfill', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Refresh cached details', exact: true }).click();
  assert.equal(await page.locator('dialog[open]').count(), 1);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  assert.equal(await page.locator('dialog[open]').count(), 0);
  await page.getByLabel('Sign-in required', { exact: true }).check();
  await page.waitForTimeout(400);
  await page.getByRole('button', { name: 'Sign in', exact: true }).waitFor();
  await page.getByLabel('Language', { exact: true }).selectOption('it');
  await page.getByRole('heading', { name: 'Impostazioni', exact: true }).waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.lang), 'it');
  await page.reload();
  await page.getByRole('heading', { name: 'Impostazioni', exact: true }).waitFor();
  await page.evaluate(() => localStorage.setItem('amazon-orders-language', 'en'));
  await page.goto(screenUrl('/', 'auth_required'));
  await page.getByRole('button', { name: 'Sign in', exact: true }).waitFor();
  await page.evaluate(() => (location.hash = '/orders/DEMO-01048'));
  await page.getByLabel('Your note', { exact: true }).fill('Synthetic test annotation');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await page.getByText('Saved locally', { exact: true }).waitFor();
  await page.evaluate(() => (location.hash = '/'));
  const popupPromise = context.waitForEvent('page');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const popup = await popupPromise;
  await popup.waitForURL('**/auth-demo.html');
  await page.getByRole('heading', { name: 'Finish signing in on Amazon' }).waitFor();
  // Polling belongs to the app shell, so switching screens must not stop it.
  await page.evaluate(() => (location.hash = '/settings'));
  await popup
    .getByRole('button', { name: 'Complete demo sign-in / Completa accesso demo' })
    .click();
  await page.getByRole('heading', { name: 'You’re connected' }).waitFor({ timeout: 7000 });
  assert.equal(await page.getByLabel('Sign-in link', { exact: true }).count(), 0);
  await popup.close();
  await page.getByRole('button', { name: 'Sign out and remove device', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('heading', { name: 'You’re connected' }).waitFor();
  await page.getByRole('button', { name: 'Sign out and remove device', exact: true }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Sign out and remove device', exact: true })
    .click();
  await page.getByRole('button', { name: 'Sign in', exact: true }).waitFor();
  // Synthetic annotation survived device removal.
  await page.evaluate(() => (location.hash = '/orders/DEMO-01048'));
  await page.getByLabel('Your note', { exact: true }).waitFor();
  assert.equal(
    await page.getByLabel('Your note', { exact: true }).inputValue(),
    'Synthetic test annotation'
  );
  await page.goto(screenUrl('/', 'auth_required'));
  await page.evaluate(() => (window.open = () => null));
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page
    .getByText('The new tab was blocked. Open or copy this link on your home network.')
    .waitFor();
  assert.match(
    await page.getByLabel('Sign-in link', { exact: true }).inputValue(),
    /^http:\/\/127\.0\.0\.1:5173\/auth-demo\.html$/
  );
  assert.equal((await page.request.get('http://127.0.0.1:5173/favicon.svg')).status(), 200);
  await context.close();
  assert.deepEqual(errors, []);
  await writeFile(
    `${output}/visual-results.json`,
    JSON.stringify(
      {
        screenshots: results.length,
        screens: results,
        checks: [
          'no horizontal overflow',
          'no runtime errors',
          'search + empty state',
          'local annotation read-back',
          '36-month warranty override read-back',
          'backfill pause read-back',
          'purge confirmation',
          'auth_required + in_progress in both languages',
          'new tab + polling success across navigation',
          'confirmed device removal preserves annotations',
          'popup-blocked copyable URL',
          'favicon returns 200',
          'Italian language persisted'
        ]
      },
      null,
      2
    )
  );
  console.log(
    JSON.stringify(
      { screenshots: results.length, output, runtimeErrors: errors, interactions: 'passed' },
      null,
      2
    )
  );
} finally {
  await browser.close();
}
