import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { apiError, mockApi, renderAt } from '../test/utils';
import { DashboardPage } from './DashboardPage';

const board = {
  dataset_count: 2,
  version_count: 4,
  rule_count: 6,
  report_count: 0,
  experiment_count: 0,
  recent_imports: [
    { dataset_id: 'ds_1', dataset_name: 'orders', version_id: 'v3', version_number: 3, row_count: 2529, origin: 'sample', rejected_row_count: 0, imported_at: '2026-10-01T10:00:00Z', status: 'active' },
  ],
  rule_status: { passed: 15, failed: 6, error: 0, not_evaluated: 1, datasets_failing: 1 },
  active_anomalies: {
    count: 1,
    items: [{ key: 'new_category:currency', category: 'new_category', label: 'Unexpected categories', severity: 'medium', title: "Unexpected values in 'currency': 'JPY' (102)", explanation: '', column: 'currency', source: 'statistics', evidence: {}, dataset_id: 'ds_1', dataset_name: 'orders', version_number: 3 }],
  },
  schema_changes: { count: 1, items: [{ change_type: 'removed', column: 'discount', from: 'float', to: null, severity: 'high', explanation: '', dataset_id: 'ds_1', dataset_name: 'orders', version_number: 3 }] },
  impact: {
    origins: [{ id: 'a1', name: 'orders', state: 'failing', impacted: 1 }],
    impacted: [{ id: 'a2', name: 'Executive revenue dashboard', kind: 'report', classification: 'unverified_risk', via: 'orders' }],
    counts: { confirmed_failure: 0, suspected_impact: 0, unverified_risk: 1, no_known_impact: 0 },
  },
  datasets: [{ dataset_id: 'ds_1', name: 'orders', kind: 'sample', version_number: 3, row_count: 2529, health: 'failing', failed_rules: 5, signals: 7, imported_at: '2026-10-01T10:00:00Z' }],
};

describe('DashboardPage', () => {
  it('shows numbers exactly as returned by the API', async () => {
    mockApi({ 'GET /dashboard': () => board });
    renderAt(<DashboardPage />);
    expect(await screen.findByText('6 failed')).toBeInTheDocument();
    expect(screen.getByText('15 passed · 0 errors · 1 not evaluated')).toBeInTheDocument();
    expect(screen.getByText("Unexpected values in 'currency': 'JPY' (102)")).toBeInTheDocument();
    expect(screen.getByText('Executive revenue dashboard')).toBeInTheDocument();
    expect(screen.getByText('Unverified risk')).toBeInTheDocument();
    expect(screen.getByText('Failing')).toBeInTheDocument();
  });

  it('offers the demo workspace when empty and reloads after loading it', async () => {
    let loaded = false;
    const { calls } = mockApi({
      'GET /dashboard': () => (loaded ? board : { ...board, dataset_count: 0 }),
      'POST /samples/load': () => {
        loaded = true;
        return { datasets: 5, versions: 7, rules: 21 };
      },
    });
    renderAt(<DashboardPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Load demo workspace' }));
    expect(await screen.findByText('6 failed')).toBeInTheDocument();
    expect(calls.filter((c) => c.path === '/samples/load')).toHaveLength(1);
  });

  it('renders API failures with the message and a retry', async () => {
    let fail = true;
    mockApi({ 'GET /dashboard': () => (fail ? apiError(500, 'internal_error', 'An unexpected error occurred.') : board) });
    renderAt(<DashboardPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('An unexpected error occurred.');
    expect(screen.getByText('Request id: req123')).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByText('6 failed')).toBeInTheDocument());
  });
});
