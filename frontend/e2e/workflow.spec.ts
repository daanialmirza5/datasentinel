import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

/**
 * The complete user journey in a real browser against the real API:
 * import → profile → quality rule → inject fault → detect → compare → trace impact → report export.
 */

const unique = Date.now().toString(36);
const ordersName = `orders_${unique}`;
const reportName = `finance report ${unique}`;

function ordersCsv(): string {
  const statuses = ['paid', 'paid', 'paid', 'refunded'];
  const rows = Array.from({ length: 400 }, (_, i) => `${i + 1},${(i % 3) + 1},${(10 + (i % 17) * 1.5).toFixed(2)},${statuses[i % 4]}`);
  return ['order_id,customer_id,amount,status', ...rows, 'broken,row'].join('\n') + '\n';
}

async function selectDataset(page: Page, name: string) {
  const picker = page.getByLabel('Dataset', { exact: true });
  const value = await picker.locator('option', { hasText: name }).getAttribute('value');
  await picker.selectOption(value ?? '');
}

test('import to report, end to end', async ({ page }) => {
  // 1. Import a dataset (with one malformed row that must be rejected and reported).
  await page.goto('/datasets');
  await page.getByRole('button', { name: 'Import data' }).first().click();
  await page.getByLabel('File').setInputFiles({ name: 'orders.csv', mimeType: 'text/csv', buffer: Buffer.from(ordersCsv()) });
  await page.getByLabel('Dataset name (optional)').fill(ordersName);
  await page.getByRole('button', { name: 'Import', exact: true }).click();
  await expect(page.getByText(`Imported ${ordersName} version 1: 400 rows × 4 columns`)).toBeVisible();
  await expect(page.getByText('1 rejected rows')).toBeVisible();

  // 2. Profile it.
  await page.getByRole('tab', { name: 'Profile' }).click();
  await expect(page.getByText('Exact', { exact: false }).first()).toBeVisible();
  await expect(page.getByRole('figure', { name: 'Distribution of amount' })).toBeVisible();

  // 3. Create and execute a quality rule.
  await page.goto('/rules');
  await selectDataset(page, ordersName);
  await page.getByRole('button', { name: 'New rule' }).click();
  await page.getByLabel('Rule type').selectOption('allowed_values');
  await page.getByLabel('Column').selectOption('status');
  await page.getByLabel('values').fill('paid, refunded');
  await page.getByLabel('Name').fill('status values');
  await page.getByLabel('Severity').selectOption('high');
  await page.getByRole('button', { name: 'Create rule' }).click();
  await expect(page.getByRole('checkbox', { name: 'Disable status values' })).toBeChecked();
  await page.getByRole('button', { name: 'Run enabled rules' }).click();
  await expect(page.getByText('All 400 values satisfy the rule.')).toBeVisible();

  // Declare a downstream consumer so impact can be traced.
  await page.goto('/lineage');
  await page.getByLabel('Asset name').fill(reportName);
  await page.getByLabel('Kind').selectOption('report');
  await page.getByRole('button', { name: 'Add asset' }).click();
  await page.getByLabel('Upstream (feeds)').selectOption({ label: ordersName });
  await page.getByLabel('Downstream (reads)').selectOption({ label: reportName });
  await page.getByRole('button', { name: 'Add dependency' }).click();
  await expect(page.getByText(`${ordersName}`).first()).toBeVisible();

  // 4. Inject a controlled fault.
  await page.goto('/lab');
  await selectDataset(page, ordersName);
  await page.getByLabel('Fault', { exact: true }).selectOption('unexpected_categories');
  await page.getByLabel('Target column').selectOption('status');
  await page.getByLabel('fraction').fill('0.1');
  await page.getByLabel('Random seed').fill('3');
  await page.getByRole('button', { name: 'Inject fault and run detection' }).click();

  // 5. Detect the resulting anomaly (scored against ground truth).
  await expect(page.getByText('Ground truth (hidden from the detector)')).toBeVisible();
  await expect(page.getByText('Detected').first()).toBeVisible();
  await expect(page.getByText(/Unexpected values in 'status'/)).toBeVisible();
  await expect(page.getByText("Rule 'status values' now fails")).toBeVisible();

  // 6. Compare the original and modified versions.
  await expect(page.getByRole('figure', { name: 'status: original vs. modified' })).toBeVisible();

  // 7. Trace downstream impact.
  await expect(page.getByText(reportName, { exact: true })).toBeVisible();
  await expect(page.getByText(`${ordersName} → ${reportName}`)).toBeVisible();
  await expect(page.getByText('Suspected impact').first()).toBeVisible();

  // 8. Generate and export a report.
  await page.getByRole('button', { name: 'Report' }).click();
  await expect(page).toHaveURL(/\/reports\?report=rpt_/);
  await expect(page.getByText('Evaluation against ground truth')).toBeVisible();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Export Markdown' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.md$/);
  const markdown = readFileSync(await download.path(), 'utf8');
  expect(markdown).toContain('## Ground truth');
  expect(markdown).toContain('Outcome: **detected**');
  expect(markdown).toContain(reportName);
});
