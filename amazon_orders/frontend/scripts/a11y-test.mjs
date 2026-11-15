import { chromium } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { writeFile } from 'node:fs/promises';
const browser = await chromium.launch({
  executablePath: '/usr/sbin/chromium',
  args: ['--no-sandbox']
});
const reports = [];
try {
  for (const mode of ['light', 'dark'])
    for (const mobile of [false, true]) {
      const context = await browser.newContext({
        reducedMotion: 'reduce',
        viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1080 },
        colorScheme: mode
      });
      const page = await context.newPage();
      for (const route of [
        '/',
        '/orders',
        '/orders/DEMO-01048',
        '/deadlines',
        '/statistics',
        '/settings'
      ]) {
        await page.goto(`http://127.0.0.1:5173/#${route}`);
        await page.waitForTimeout(600);
        const results = await new AxeBuilder({ page })
          .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
          .analyze();
        reports.push({
          mode,
          mobile,
          route,
          violations: results.violations.map((v) => ({
            id: v.id,
            impact: v.impact,
            description: v.description,
            nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary }))
          }))
        });
      }
      await context.close();
    }
  await writeFile(
    new URL('../../../docs/screenshots/accessibility-results.json', import.meta.url),
    JSON.stringify(reports, null, 2)
  );
  const failures = reports.filter((r) => r.violations.length);
  console.log(JSON.stringify(failures, null, 2));
  if (failures.length) process.exitCode = 1;
  else console.log('24 screen/theme/device combinations: zero WCAG A/AA violations.');
} finally {
  await browser.close();
}
