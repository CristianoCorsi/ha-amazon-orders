// Requires the disposable API fixture on 18765 and a production `pnpm build`.
import { chromium } from '@playwright/test';
import { createServer } from 'node:http';
import { writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const prefix = '/api/hassio_ingress/SYNTHETIC-test-token/';
const backend = 'http://127.0.0.1:18765';
const proxy = createServer(async (req, res) => {
  try {
    if (!req.url?.startsWith(prefix)) {
      res.writeHead(404).end();
      return;
    }
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const response = await fetch(`${backend}/${req.url.slice(prefix.length)}`, {
      method: req.method,
      headers: {
        'x-ingress-path': prefix.slice(0, -1),
        'content-type': req.headers['content-type'] ?? 'application/json'
      },
      body: ['GET', 'HEAD'].includes(req.method ?? 'GET') ? undefined : Buffer.concat(chunks)
    });
    res.writeHead(response.status, {
      'Content-Type': response.headers.get('content-type') ?? 'application/octet-stream'
    });
    res.end(Buffer.from(await response.arrayBuffer()));
  } catch (e) {
    res.writeHead(502).end(String(e));
  }
});
await new Promise((resolve) => proxy.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${proxy.address().port}`;
const browser = await chromium.launch({
  executablePath: '/usr/sbin/chromium',
  args: ['--no-sandbox']
});
const errors = [],
  requests = [],
  failed = [];
try {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1080 },
    locale: 'en-GB',
    reducedMotion: 'reduce'
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('request', (r) => requests.push(new URL(r.url()).pathname));
  page.on('response', (r) => {
    if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
  });
  await context.route('**/www.amazon.it/**', (r) => r.abort());
  for (const route of ['/', '/orders', '/deadlines', '/statistics', '/settings']) {
    await page.goto(`${origin}${prefix}#${route}`);
    await page.locator('main h1').waitFor();
    await page.waitForTimeout(750);
    assert.equal(
      await page.locator('.error-alert,main .empty-state[role="alert"]').count(),
      0,
      `Real API screen ${route} has no errors`
    );
    assert.equal(await page.locator('.demo-badge').count(), 0, 'Production build excludes demo');
  }
  await page.goto(`${origin}${prefix}#/orders`);
  await page.locator('.order-row').first().waitFor();
  await page.locator('.order-row').first().click();
  await page.getByLabel('Your note', { exact: true }).first().waitFor();
  const currentHash = new URL(page.url()).hash;
  await page
    .getByLabel('Your note', { exact: true })
    .first()
    .fill('Synthetic integration verification');
  await page.getByLabel('Warranty duration', { exact: true }).first().selectOption('months');
  await page.getByLabel('Number of months').first().fill('36');
  await page.getByRole('button', { name: 'Save changes' }).first().click();
  await page.getByText('Saved locally', { exact: true }).first().waitFor();
  await page.reload();
  await page.getByLabel('Your note', { exact: true }).first().waitFor();
  assert.equal(
    await page.getByLabel('Your note', { exact: true }).first().inputValue(),
    'Synthetic integration verification'
  );
  assert.equal(await page.getByLabel('Number of months').first().inputValue(), '36');
  assert.equal(new URL(page.url()).hash, currentHash, 'Hash detail survives prefix reload');
  await page.goto(`${origin}${prefix}#/orders`);
  await page.locator('.order-row').first().waitFor();
  await page.getByLabel('Sort orders').selectOption('date_asc');
  await page.waitForTimeout(800);
  assert.equal(await page.locator('main .empty-state[role="alert"]').count(), 0);
  const csv = await context.request.get(`${origin}${prefix}api/export.csv`);
  assert.equal(csv.status(), 200);
  assert.ok((await csv.text()).includes('Synthetic integration verification'));
  const ics = await context.request.get(`${origin}${prefix}calendar.ics`);
  assert.equal(ics.status(), 200);
  assert.ok((await ics.text()).includes('BEGIN:VCALENDAR'));
  assert.deepEqual(errors, []);
  assert.deepEqual(failed, []);
  assert.ok(
    requests.filter((p) => p.includes('/_app/')).every((p) => p.startsWith(prefix)),
    'All assets stay inside dynamic prefix'
  );
  assert.ok(
    requests.some((p) => p === `${prefix}api/status`),
    'API path stays inside prefix'
  );
  await context.close();
  // Synthetic same-origin HA host verifies parent theme + language and live changes.
  const host = await browser.newContext({ locale: 'en-GB' });
  const hostPage = await host.newPage();
  await host.route(`${origin}/ha-fixture`, (r) =>
    r.fulfill({
      contentType: 'text/html',
      body: `<!doctype html><html style="--primary-color:#03a9f4;--card-background-color:#18252d;--primary-background-color:#101b21;--primary-text-color:#e0ecf0;--secondary-text-color:#a8bcc5"><body><home-assistant></home-assistant><script>document.querySelector('home-assistant').hass={language:'it',themes:{darkMode:true}};</script><iframe title="Synthetic HA Ingress" src="${prefix}" style="width:100%;height:900px"></iframe></body></html>`
    })
  );
  await hostPage.goto(`${origin}/ha-fixture`);
  const frame = hostPage.frameLocator('iframe');
  await frame.getByRole('heading', { name: 'Panoramica', exact: true }).waitFor();
  assert.equal(await frame.locator('html').getAttribute('data-theme'), 'dark');
  assert.equal(
    await frame
      .locator('html')
      .evaluate((el) => getComputedStyle(el).getPropertyValue('--primary').trim()),
    '#03a9f4'
  );
  await hostPage.evaluate(() => {
    document.querySelector('home-assistant').hass.themes.darkMode = false;
    document.documentElement.style.setProperty('--primary-color', '#00796b');
  });
  await hostPage.waitForTimeout(300);
  assert.equal(await frame.locator('html').getAttribute('data-theme'), 'light');
  assert.equal(
    await frame
      .locator('html')
      .evaluate((el) => getComputedStyle(el).getPropertyValue('--primary').trim()),
    '#00796b'
  );
  await host.close();
  const result = {
    productionScreens: 6,
    realApi: 'passed',
    annotationAndWarrantyReadBack: 'passed',
    csv: 'passed',
    ics: 'passed',
    dynamicPrefix: prefix,
    hashReload: 'passed',
    parentThemeAndLocale: 'passed',
    liveParentThemeChange: 'passed',
    runtimeErrors: errors,
    failedRequests: failed
  };
  await writeFile(
    new URL('../../../docs/screenshots/integration-results.json', import.meta.url),
    JSON.stringify(result, null, 2)
  );
  console.log(JSON.stringify(result, null, 2));
} finally {
  await browser.close();
  await new Promise((resolve) => proxy.close(resolve));
}
