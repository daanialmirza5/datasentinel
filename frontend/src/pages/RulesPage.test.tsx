import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { Rule } from '../api/types';
import { dataset, page } from '../test/fixtures';
import { apiError, mockApi, renderAt, type RecordedCall } from '../test/utils';
import { RulesPage } from './RulesPage';

const ruleTypes = {
  severities: ['low', 'medium', 'high', 'critical'],
  types: [
    { rule_type: 'not_null', label: 'No missing values', description: 'No nulls', requires_column: true, scope: 'row', params_schema: { properties: { max_null_pct: { type: 'number', default: 0 } } } },
    {
      rule_type: 'range', label: 'Numeric range', description: 'Within bounds', requires_column: true, scope: 'row',
      params_schema: { properties: { min: { anyOf: [{ type: 'number' }, { type: 'null' }] }, max: { anyOf: [{ type: 'number' }, { type: 'null' }] }, inclusive: { type: 'boolean', default: true } } },
    },
    { rule_type: 'row_count', label: 'Row count', description: 'Rows', requires_column: false, scope: 'dataset', params_schema: { properties: { min: { anyOf: [{ type: 'integer' }, { type: 'null' }] } } } },
  ],
};

const existing: Rule = {
  id: 'rule_1', dataset_id: 'ds_orders', name: 'amount present', rule_type: 'not_null', column_name: 'amount', params: { max_null_pct: 0 },
  severity: 'high', enabled: true, description: '', created_at: '', updated_at: '',
};

function routes(overrides: Record<string, (call: RecordedCall) => unknown> = {}) {
  return mockApi({
    'GET /datasets': () => page([dataset()]),
    'GET /rule-types': () => ruleTypes,
    'GET /datasets/ds_orders/rules': () => [existing],
    'GET /datasets/ds_orders/rules/suggestions': () => ({ suggestions: [{ name: 'order_id unique', rule_type: 'unique', column_name: 'order_id', params: {}, severity: 'high', reason: 'All distinct' }] }),
    'POST /datasets/ds_orders/rules': (call: RecordedCall) => ({ ...existing, id: 'rule_2', ...(call.body as Partial<Rule>) }),
    'PATCH /rules/rule_1': (call: RecordedCall) => ({ ...existing, ...(call.body as Partial<Rule>) }),
    'POST /datasets/ds_orders/validate': () => ({
      id: 'run_1', dataset_id: 'ds_orders', version_id: 'ver_1', version_number: 1, trigger: 'manual', started_at: '2026-10-01T10:00:00Z', finished_at: null,
      summary: { total: 1, passed: 0, failed: 1, error: 0, not_evaluated: 0, health: 'failing' },
      results: [{ id: 'res_1', rule_id: 'rule_1', rule_name: 'amount present', rule_type: 'not_null', column_name: 'amount', severity: 'high', status: 'failed', evaluated_count: 120, violation_count: 3, violation_pct: 2.5, message: '3 of 120 rows are missing', recommendation: 'Check joins', examples: [{ row: 7, values: { amount: null } }], details: {} }],
    }),
    ...overrides,
  });
}

describe('RulesPage', () => {
  it('creates a rule with typed parameters', async () => {
    const { calls } = routes();
    renderAt(<RulesPage />, '/rules?dataset=ds_orders');
    await userEvent.click(await screen.findByRole('button', { name: 'New rule' }));
    await userEvent.selectOptions(screen.getByLabelText('Rule type'), 'range');
    await userEvent.selectOptions(screen.getByLabelText('Column'), 'amount');
    await userEvent.type(screen.getByLabelText('min'), '0');
    await userEvent.type(screen.getByLabelText('max'), '10000');
    await userEvent.type(screen.getByLabelText('Name'), 'amount range');
    await userEvent.click(screen.getByRole('button', { name: 'Create rule' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/datasets/ds_orders/rules')).toBe(true));
    const post = calls.find((c) => c.method === 'POST' && c.path === '/datasets/ds_orders/rules');
    expect(post?.body).toEqual({ name: 'amount range', rule_type: 'range', column_name: 'amount', params: { min: 0, max: 10000 }, severity: 'medium' });
  });

  it('omits the column for dataset-level rules', async () => {
    const { calls } = routes();
    renderAt(<RulesPage />, '/rules?dataset=ds_orders');
    await userEvent.click(await screen.findByRole('button', { name: 'New rule' }));
    await userEvent.selectOptions(screen.getByLabelText('Rule type'), 'row_count');
    expect(screen.queryByLabelText('Column')).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('min'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'Create rule' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ column_name: null, params: { min: 1000 } }));
  });

  it('edits an existing rule and toggles it', async () => {
    const { calls } = routes();
    renderAt(<RulesPage />, '/rules?dataset=ds_orders');
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const threshold = screen.getByLabelText('max null pct');
    expect(threshold).toHaveValue(0);
    await userEvent.clear(threshold);
    await userEvent.type(threshold, '5');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({ params: { max_null_pct: 5 } }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Disable amount present' }));
    await waitFor(() => expect(calls.filter((c) => c.method === 'PATCH').at(-1)?.body).toEqual({ enabled: false }));
  });

  it('runs rules and shows violations with examples', async () => {
    routes();
    renderAt(<RulesPage />, '/rules?dataset=ds_orders');
    await userEvent.click(await screen.findByRole('button', { name: 'Run enabled rules' }));
    expect(await screen.findByText('3 of 120 rows are missing')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('→ Check joins')).toBeInTheDocument();
    expect(screen.getByText(/row 7:/)).toBeInTheDocument();
  });

  it('surfaces server-side validation errors on the form', async () => {
    routes({ 'POST /datasets/ds_orders/rules': () => apiError(422, 'validation_failed', 'Invalid rule parameters', [{ location: ['min'], message: 'Provide at least one of min or max' }]) });
    renderAt(<RulesPage />, '/rules?dataset=ds_orders');
    await userEvent.click(await screen.findByRole('button', { name: 'New rule' }));
    await userEvent.selectOptions(screen.getByLabelText('Rule type'), 'range');
    await userEvent.click(screen.getByRole('button', { name: 'Create rule' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Invalid rule parameters');
    expect(alert).toHaveTextContent('Provide at least one of min or max');
  });

  it('adds a suggested rule', async () => {
    const { calls } = routes();
    renderAt(<RulesPage />, '/rules?dataset=ds_orders');
    expect(await screen.findByText('All distinct')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ rule_type: 'unique', column_name: 'order_id' }));
  });
});
