import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { dataset, page, version } from '../test/fixtures';
import { mockApi, renderAt } from '../test/utils';
import { DatasetsPage } from './DatasetsPage';

const customers = dataset({ id: 'ds_cust', name: 'customers', current_version: version({ id: 'ver_c', dataset_id: 'ds_cust' }) });

const profile = {
  dataset_id: 'ds_orders', version_id: 'ver_1', version_number: 1, computed_at: '2026-10-01T10:00:00Z', duration_ms: 12.5, cached: true,
  profile: {
    row_count: 120, column_count: 1, duplicate_rows: 2, duplicate_pct: 1.67, missing_cells: 3, missing_pct: 2.5, exact: true,
    notes: ['All statistics are exact over every row; histograms are binned summaries.'],
    columns: [{
      name: 'amount', type: 'float', non_null_count: 117, null_count: 3, null_pct: 2.5, distinct_count: 100, distinct_pct: 85, unique: false,
      duplicate_value_count: 17, invalid_count: 1, invalid_pct: 0.85, invalid_examples: ['n/a?'], is_constant: false, is_categorical: false,
      mixed: false, notes: [], top_values: [], min: 1.5, max: 950, mean: 42.25, median: 30.1, std: 12.75,
      quantiles: { p05: 3, p95: 120 }, outliers: { iqr_count: 4, mad_count: 2 },
      histogram: { kind: 'bins', edges: [0, 500, 1000], counts: [110, 7] },
    }],
  },
};

function routes() {
  return mockApi({
    'GET /datasets': () => page([dataset(), customers]),
    'GET /datasets/ds_orders/versions': () => [version(), version({ id: 'ver_2', version_number: 2, status: 'quarantined' })],
    'GET /datasets/ds_cust/versions': () => [version({ id: 'ver_c', dataset_id: 'ds_cust' })],
    'GET /datasets/ds_orders/profile': () => profile,
    'GET /datasets/ds_orders/preview': (call) => ({
      dataset_id: 'ds_orders', version_id: 'ver_1', columns: version().schema, total: 60,
      offset: Number(call.query.get('offset')), limit: 25,
      rows: [[String(Number(call.query.get('offset')) + 1), null, 'paid']], row_numbers: [Number(call.query.get('offset')) + 1],
    }),
    'GET /datasets/ds_orders/rejected-rows': () => ({ total: 0, truncated: false, rows: [] }),
    'POST /datasets/ds_orders/versions/ver_1/quarantine': () => version({ status: 'quarantined' }),
  });
}

describe('DatasetsPage', () => {
  it('lists datasets and switches the selected dataset', async () => {
    const { calls } = routes();
    renderAt(<DatasetsPage />, '/datasets?dataset=ds_orders');
    expect(await screen.findByRole('heading', { name: 'orders' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /customers/ }));
    expect(await screen.findByRole('heading', { name: 'customers' })).toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.path === '/datasets/ds_cust/versions')).toBe(true));
  });

  it('shows version history with quarantine controls', async () => {
    const { calls } = routes();
    renderAt(<DatasetsPage />, '/datasets?dataset=ds_orders');
    const table = await screen.findByRole('table');
    expect(within(table).getByText('Quarantined')).toBeInTheDocument();
    await userEvent.click(within(table).getByRole('button', { name: 'Quarantine' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path.endsWith('/quarantine'))).toBe(true));
  });

  it('displays exact profile statistics', async () => {
    routes();
    renderAt(<DatasetsPage />, '/datasets?dataset=ds_orders');
    await userEvent.click(await screen.findByRole('tab', { name: 'Profile' }));
    expect(await screen.findByText('3 (2.5%)')).toBeInTheDocument();
    expect(screen.getByText('42.25 / 30.1')).toBeInTheDocument();
    expect(screen.getByText('2 / 4')).toBeInTheDocument();
    expect(screen.getByText(/1 \(e\.g\. "n\/a\?"\)/)).toBeInTheDocument();
    expect(screen.getByText(/All statistics are exact/)).toBeInTheDocument();
    expect(screen.getByRole('figure', { name: 'Distribution of amount' })).toBeInTheDocument();
  });

  it('paginates the preview', async () => {
    const { calls } = routes();
    renderAt(<DatasetsPage />, '/datasets?dataset=ds_orders');
    await userEvent.click(await screen.findByRole('tab', { name: 'Preview' }));
    expect(await screen.findByText('Rows 1–25 of 60')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText('Rows 26–50 of 60')).toBeInTheDocument();
    expect(calls.filter((c) => c.path.endsWith('/preview')).map((c) => c.query.get('offset'))).toEqual(['0', '25']);
    expect(screen.getAllByText('null').length).toBeGreaterThan(0);
  });
});
