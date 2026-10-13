// Captures screenshots of the running application for the README (docs/screenshots).
// Usage: start the backend + frontend, load the demo workspace, then
//   node scripts/capture-screenshots.mjs [baseUrl] [outDir]
// Uses the locally installed Microsoft Edge (channel "msedge"); set PW_CHANNEL=chromium to use
// Playwright's bundled Chromium instead.
import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const base = process.argv[2] ?? 'http://127.0.0.1:5173';
const out = resolve(process.argv[3] ?? '../docs/screenshots');
mkdirSync(out, { recursive: true });

const channel = process.env.PW_CHANNEL ?? 'msedge';
const browser = await chromium.launch(channel === 'chromium' ? {} : { channel });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });

async function shot(name, path, prepare) {
  await page.goto(`${base}${path}`, { waitUntil: 'networkidle' });
  if (prepare) await prepare();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
  console.log(`captured ${name}`);
}

const datasets = await (await fetch(`${base}/api/v1/datasets`)).json();
const orders = datasets.items.find((d) => d.name === 'orders');
const sensors = datasets.items.find((d) => d.name === 'sensor_readings');

await shot('01-dashboard', '/');
await shot('02-dataset-profile', `/datasets?dataset=${orders.id}`, async () => {
  await page.getByRole('tab', { name: 'Profile' }).click();
  await page.getByText('Exact statistics', { exact: false }).first().waitFor({ timeout: 2000 }).catch(() => {});
});
await shot('03-quality-rules', `/rules?dataset=${orders.id}`, async () => {
  await page.getByRole('button', { name: 'Run enabled rules' }).click();
  await page.getByText('Validation results').waitFor();
});
await shot('04-drift', `/drift?dataset=${orders.id}`, async () => {
  await page.getByText('Column comparisons').waitFor();
});
await shot('05-lineage-impact', '/lineage', async () => {
  await page.getByRole('button', { name: 'orders', exact: true }).click();
  await page.getByRole('button', { name: 'Trace downstream impact' }).click();
  await page.getByRole('heading', { name: 'Recommended actions' }).or(page.getByText('Recommended actions', { exact: true })).first().waitFor();
});
await shot('06-fault-lab', `/lab?dataset=${orders.id}`, async () => {
  await page.getByLabel('Fault', { exact: true }).selectOption('numeric_outliers');
  await page.getByLabel('Target column').selectOption('amount');
  await page.getByRole('button', { name: 'Inject fault and run detection' }).click();
  await page.getByText('Ground truth (hidden from the detector)').waitFor();
});
await shot('07-anomalies', `/datasets?dataset=${sensors.id}`, async () => {
  await page.getByRole('tab', { name: 'Anomalies' }).click();
  await page.getByText('Time-series deviations').waitFor();
});
await shot('08-reports', '/reports', async () => {
  await page.getByLabel('Dataset (current version vs. previous)').selectOption({ label: 'orders' });
  await page.getByRole('button', { name: 'Generate report' }).click();
  await page.getByRole('heading', { name: 'Recommended actions' }).or(page.getByText('Recommended actions', { exact: true })).first().waitFor();
});
await browser.close();
