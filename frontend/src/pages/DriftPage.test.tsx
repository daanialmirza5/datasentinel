import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { dataset, page, version } from '../test/fixtures';
import { mockApi, renderAt } from '../test/utils';
import { DriftPage } from './DriftPage';

const ok = {
  status: 'ok', dataset_id: 'ds_orders',
  base: { id: 'ver_1', version_number: 1, imported_at: '', row_count: 2550, status: 'active' },
  candidate: { id: 'ver_2', version_number: 2, imported_at: '', row_count: 2529, status: 'active' },
  row_count: { base: 2550, candidate: 2529, change_pct: -0.82 },
  schema_changes: [{ change_type: 'removed', column: 'discount', from: 'float', to: null, severity: 'high', explanation: 'Consumers selecting it will fail.' }],
  signals: [{ key: 'null_rate_increase:ship_country', category: 'null_rate_increase', label: 'Missing values increased', severity: 'medium', title: "Missing 'ship_country' values rose 1.1% → 18.5%", explanation: 'two_proportion_z, p=1e-90', column: 'ship_country', source: 'statistics', evidence: { delta_pp: 17.4 } }],
  column_comparisons: [
    { column: 'ship_country', base_type: 'string', candidate_type: 'string', identifier: false, base_null_pct: 1.1, candidate_null_pct: 18.5, null_rate: { base_pct: 1.1, candidate_pct: 18.5, delta_pp: 17.4 }, chart: { kind: 'categorical', labels: ['US', 'DE'], base: [0.4, 0.1], candidate: [0.3, 0.1] } },
    { column: 'quantity', base_type: 'integer', candidate_type: 'integer', identifier: false, base_null_pct: 0, candidate_null_pct: 0 },
  ],
  summary: { signal_count: 1, actionable_signal_count: 1, max_severity: 'medium' },
};

describe('DriftPage', () => {
  it('explains schema changes and signals with evidence', async () => {
    mockApi({
      'GET /datasets': () => page([dataset()]),
      'GET /datasets/ds_orders/versions': () => [version(), version({ id: 'ver_2', version_number: 2 })],
      'GET /datasets/ds_orders/drift': () => ok,
    });
    renderAt(<DriftPage />, '/drift?dataset=ds_orders');
    expect(await screen.findByText("Missing 'ship_country' values rose 1.1% → 18.5%")).toBeInTheDocument();
    expect(screen.getByText('Consumers selecting it will fail.')).toBeInTheDocument();
    expect(screen.getByText(/Rows 2,550 → 2,529/)).toBeInTheDocument();
    // Only columns with signals are shown by default.
    expect(screen.getByText(/missing 1.1% → 18.5%/)).toBeInTheDocument();
    expect(screen.queryByText('quantity')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Only columns with signals' }));
    expect(screen.getByText('quantity')).toBeInTheDocument();
  });

  it('requests a specific comparison when versions are chosen', async () => {
    const { calls } = mockApi({
      'GET /datasets': () => page([dataset()]),
      'GET /datasets/ds_orders/versions': () => [version(), version({ id: 'ver_2', version_number: 2 })],
      'GET /datasets/ds_orders/drift': () => ok,
    });
    renderAt(<DriftPage />, '/drift?dataset=ds_orders');
    await screen.findByText('Column comparisons');
    await userEvent.selectOptions(screen.getByLabelText('Baseline version'), 'ver_2');
    await screen.findByText('Column comparisons');
    expect(calls.filter((c) => c.path.endsWith('/drift')).at(-1)?.query.get('base_version_id')).toBe('ver_2');
  });

  it('explains when there is nothing to compare', async () => {
    mockApi({
      'GET /datasets': () => page([dataset()]),
      'GET /datasets/ds_orders/versions': () => [version()],
      'GET /datasets/ds_orders/drift': () => ({ status: 'no_baseline', dataset_id: 'ds_orders', candidate: ok.candidate, message: 'Drift needs at least two versions.' }),
    });
    renderAt(<DriftPage />, '/drift?dataset=ds_orders');
    expect(await screen.findByText('Drift needs at least two versions.')).toBeInTheDocument();
  });
});
