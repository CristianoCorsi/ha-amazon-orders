import { chromium } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { writeFile } from 'node:fs/promises';
import { screens, screenUrl } from './scenarios.mjs';
const browser = await chromium.launch({
  executablePath: '/usr/sbin/chromium',
  args: ['--no-sandbox']
});
const reports = [];
try {
  for (const language of ['en', 'it'])
    for (const mode of ['light', 'dark'])
      for (const mobile of [false, true]) {
        const context = await browser.newContext({
          reducedMotion: 'reduce',
          viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1080 },
          colorScheme: mode
        });
        const page = await context.newPage();
        await page.addInitScript(
          ({ language, mode }) => {
            localStorage.setItem('amazon-orders-language', language);
            localStorage.setItem('amazon-orders-theme', mode);
          },
          { language, mode }
        );
        for (const [name, route, authState] of screens) {
          await page.goto(screenUrl(route, authState));
          await page.waitForTimeout(600);
          const results = await new AxeBuilder({ page })
            .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
            .analyze();
          reports.push({
            language,
            mode,
            mobile,
            name,
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
  else
    console.log(
      `${reports.length} screen/state/language/theme/device combinations: zero WCAG A/AA violations.`
    );
} finally {
  await browser.close();
}
