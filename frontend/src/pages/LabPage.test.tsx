import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { Experiment } from '../api/types';
import { dataset, page } from '../test/fixtures';
import { mockApi, renderAt } from '../test/utils';
import { LabPage } from './LabPage';

const faults = {
  fault_types: [
    { fault_type: 'missing_values', label: 'Missing-value injection', description: 'Blank out values', column_kind: 'any', expected_signals: ['null_rate_increase'], note: '', eligible_columns: ['amount', 'status'], params_schema: { properties: { column: { anyOf: [{ type: 'string' }, { type: 'null' }] }, fraction: { type: 'number', default: 0.1 } } } },
    { fault_type: 'referential_integrity', label: 'Referential integrity violation', description: 'Orphans', column_kind: 'key', expected_signals: ['referential_integrity'], note: 'Needs a foreign_key rule on the column.', eligible_columns: [], params_schema: { properties: { column: { anyOf: [{ type: 'string' }, { type: 'null' }] } } } },
  ],
};

const experiment = (overrides: Partial<Experiment> = {}): Experiment => ({
  id: 'exp_1', dataset_id: 'ds_orders', dataset_name: 'orders', base_version_id: 'ver_1', base_version_number: 1, lab_dataset_id: 'ds_lab', result_version_id: 'ver_lab',
  fault_type: 'missing_values', params: { column: 'amount', fraction: 0.2 }, seed: 7, status: 'completed', duration_ms: 120, created_at: '2026-10-01T10:00:00Z', expires_at: null,
  outcome: 'detected', detected: true, counts: { expected: 1, matched: 1 },
  ground_truth: { scope: 'column', affected_columns: ['amount'], affected_rows: 24, expected: { primary: ['null_rate_increase'], accepted: [] }, examples: [{ row: 3, before: { amount: '10.5' }, after: { amount: null } }] },
  detection: {
    signals: [
      { key: 'null_rate_increase:amount', category: 'null_rate_increase', label: '', severity: 'medium', title: "Missing 'amount' values rose 0% → 20%", explanation: 'z-test', column: 'amount', source: 'statistics', evidence: {} },
      { key: 'distribution_shift:status', category: 'distribution_shift', label: '', severity: 'low', title: 'status drifted', explanation: 'noise', column: 'status', source: 'statistics', evidence: {} },
    ],
    schema_changes: [], column_comparisons: [], row_count: { base: 120, candidate: 120 },
  },
  evaluation: {
    outcome: 'detected', detected: true,
    expected_signals: [{ category: 'null_rate_increase', column: 'amount' }], matched_signals: [{ category: 'null_rate_increase', column: 'amount' }], missed_signals: [],
    true_positives: [{ key: 'null_rate_increase:amount', category: 'null_rate_increase', column: 'amount', severity: 'medium', title: '', source: 'statistics' }],
    false_positives: [{ key: 'distribution_shift:status', category: 'distribution_shift', column: 'status', severity: 'low', title: '', source: 'statistics' }],
    signal_precision: 0.5, modified_sha256: 'f'.repeat(64), base_rows: 120, modified_rows: 120,
    simulated_impact: { simulated_origin_state: 'anomalous', impacted: [{ id: 'a2', name: 'revenue job', kind: 'transformation', distance: 1, path: ['orders', 'revenue job'], path_ids: [], classification: 'unverified_risk' }] },
  },
  ...overrides,
});

function routes() {
  return mockApi({
    'GET /datasets': () => page([dataset()]),
    'GET /experiments/fault-types': () => faults,
    'GET /experiments': () => page([]),
    'POST /experiments': () => experiment(),
    'POST /experiments/exp_1/regenerate': () => experiment({ created_at: '2026-10-01T11:00:00Z' }),
    'DELETE /experiments/exp_1': () => ({ deleted: true }),
  });
}

describe('LabPage', () => {
  it('runs a seeded scenario and shows ground-truth evaluation', async () => {
    const { calls } = routes();
    renderAt(<LabPage />, '/lab?dataset=ds_orders');
    await userEvent.selectOptions(await screen.findByLabelText('Target column'), 'amount');
    await userEvent.type(screen.getByLabelText('fraction'), '0.2');
    await userEvent.clear(screen.getByLabelText('Random seed'));
    await userEvent.type(screen.getByLabelText('Random seed'), '7');
    await userEvent.click(screen.getByRole('button', { name: 'Inject fault and run detection' }));

    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ dataset_id: 'ds_orders', fault_type: 'missing_values', params: { column: 'amount', fraction: 0.2 }, seed: 7 }));
    expect(await screen.findByText('Ground truth (hidden from the detector)')).toBeInTheDocument();
    expect(screen.getByText('True positive')).toBeInTheDocument();
    expect(screen.getByText('False positive')).toBeInTheDocument();
    expect(screen.getByText('signal precision 50%')).toBeInTheDocument();
    expect(screen.getByText('{"amount":"10.5"}')).toBeInTheDocument();
    expect(screen.getByText('{"amount":null}')).toBeInTheDocument();
    expect(screen.getByText('revenue job')).toBeInTheDocument();
  });

  it('warns about faults that need declared constraints', async () => {
    routes();
    renderAt(<LabPage />, '/lab?dataset=ds_orders');
    await userEvent.selectOptions(await screen.findByLabelText('Fault', { selector: 'select' }), 'referential_integrity');
    expect(screen.getByText(/Needs a foreign_key rule on the column/)).toBeInTheDocument();
    expect(screen.getByText('No suitable column in this dataset.')).toBeInTheDocument();
  });

  it('regenerates reproducibly and resets', async () => {
    const { calls } = routes();
    renderAt(<LabPage />, '/lab?dataset=ds_orders');
    await userEvent.click(await screen.findByRole('button', { name: 'Inject fault and run detection' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Regenerate' }));
    expect(await screen.findByText(/byte-identical \(SHA-256 matches\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(await screen.findByText('Run a scenario')).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'DELETE' && c.path === '/experiments/exp_1')).toBe(true);
  });
});
