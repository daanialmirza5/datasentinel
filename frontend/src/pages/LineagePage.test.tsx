import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { apiError, mockApi, renderAt } from '../test/utils';
import { LineagePage } from './LineagePage';

// React Flow needs real layout; render nodes as plain buttons so interaction logic can be tested.
vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ nodes, onNodeClick, children }: { nodes: { id: string; data: { asset: { name: string }; impact?: string } }[]; onNodeClick: (e: unknown, n: { id: string }) => void; children: ReactNode }) => (
    <div data-testid="flow">
      {nodes.map((n) => (
        <button key={n.id} type="button" data-impact={n.data.impact ?? ''} onClick={() => onNodeClick(null, n)}>
          node:{n.data.asset.name}
        </button>
      ))}
      {children}
    </div>
  ),
  Background: () => null,
  Controls: () => null,
  Handle: () => null,
  Position: { Left: 'left', Right: 'right' },
}));

const node = (id: string, name: string, kind: string, state = 'no_checks') => ({
  id, name, kind, description: '', owner: '', dataset_id: kind === 'dataset' ? `ds_${id}` : null, position: { x: 0, y: 0 },
  health: { state, failed_rule_count: 0, signal_count: 0 }, upstream_count: 0, downstream_count: 0,
});

const graph = {
  nodes: [node('a1', 'orders', 'dataset', 'failing'), node('a2', 'revenue job', 'transformation'), node('a3', 'exec report', 'report')],
  edges: [{ id: 'e1', source: 'a1', target: 'a2', description: '' }, { id: 'e2', source: 'a2', target: 'a3', description: '' }],
  cycles: [],
};

const details = {
  id: 'a1', name: 'orders', kind: 'dataset', description: 'Monthly exports', owner: 'platform', dataset_id: 'ds_a1',
  health: { state: 'failing', version_number: 3, failed_rules: [{ rule_name: 'currency values', severity: 'high', violation_count: 102, message: '102 values not allowed' }], schema_changes: [] },
  upstream: [], downstream: [{ id: 'a2', name: 'revenue job', kind: 'transformation', distance: 1, path: ['orders', 'revenue job'] }, { id: 'a3', name: 'exec report', kind: 'report', distance: 2, path: ['orders', 'revenue job', 'exec report'] }],
  versions: [{ id: 'v3', version_number: 3, row_count: 2529, status: 'active', imported_at: '' }],
};

const impact = {
  origin: { id: 'a1', name: 'orders', health: details.health },
  origin_state: 'failing',
  assessment: "'orders' has confirmed failures (1 failed rule(s)). 2 downstream asset(s) may be affected.",
  direct: [], transitive: [],
  impacted: [
    { id: 'a2', name: 'revenue job', kind: 'transformation', distance: 1, path: ['orders', 'revenue job'], path_ids: ['a1', 'a2'], classification: 'suspected_impact', evidence: ['Depends on orders'] },
    { id: 'a3', name: 'exec report', kind: 'report', distance: 2, path: ['orders', 'revenue job', 'exec report'], path_ids: ['a1', 'a2', 'a3'], classification: 'unverified_risk', evidence: ['Depends on orders'] },
  ],
  counts: { confirmed_failure: 0, suspected_impact: 1, unverified_risk: 1, no_known_impact: 0 },
  restore_candidate: { version_number: 2, evidence: 'passed all 11 enabled rules' },
  recommendations: [
    { priority: 1, kind: 'contain', title: "Quarantine version 3 of 'orders'", rationale: 'High-severity failures', evidence: [], action: { type: 'quarantine_version', dataset_id: 'ds_a1', version_id: 'v3' } },
    { priority: 2, kind: 'recover', title: 'Restore the previously valid version 2', rationale: 'Version 2 passed', evidence: [] },
  ],
};

describe('LineagePage', () => {
  it('selects a node, shows its dependencies and traces impact', async () => {
    mockApi({ 'GET /lineage': () => graph, 'GET /lineage/a1': () => details, 'GET /lineage/a1/impact': () => impact });
    renderAt(<LineagePage />);
    await userEvent.click(await screen.findByRole('button', { name: 'node:orders' }));
    expect(await screen.findByText('currency values: 102 values not allowed')).toBeInTheDocument();
    expect(screen.getByText('2 hops')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Trace downstream impact' }));
    expect(await screen.findByText(impact.assessment)).toBeInTheDocument();
    expect(screen.getByText('orders → revenue job → exec report')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'node:revenue job' })).toHaveAttribute('data-impact', 'suspected_impact');
    expect(screen.getByRole('button', { name: 'node:exec report' })).toHaveAttribute('data-impact', 'unverified_risk');
    expect(screen.getByText('Restore the previously valid version 2')).toBeInTheDocument();
  });

  it('navigates to a downstream asset from the details panel', async () => {
    const { calls } = mockApi({
      'GET /lineage': () => graph, 'GET /lineage/a1': () => details,
      'GET /lineage/a3': () => ({ ...details, id: 'a3', name: 'exec report', kind: 'report', dataset_id: null, health: { state: 'no_checks' }, downstream: [], versions: [] }),
    });
    renderAt(<LineagePage />);
    await userEvent.click(await screen.findByRole('button', { name: 'node:orders' }));
    await userEvent.click(await screen.findByRole('button', { name: 'exec report' }));
    await waitFor(() => expect(calls.some((c) => c.path === '/lineage/a3')).toBe(true));
    expect(await screen.findByText('No own checks')).toBeInTheDocument();
  });

  it('shows the cycle explanation when a dependency is rejected', async () => {
    mockApi({
      'GET /lineage': () => graph,
      'POST /lineage/edges': () => apiError(409, 'conflict', 'Lineage must be acyclic: this dependency would create the cycle orders → revenue job → exec report → orders'),
    });
    renderAt(<LineagePage />);
    await screen.findByRole('button', { name: 'node:orders' });
    await userEvent.selectOptions(screen.getByLabelText('Upstream (feeds)'), 'a3');
    await userEvent.selectOptions(screen.getByLabelText('Downstream (reads)'), 'a1');
    await userEvent.click(screen.getByRole('button', { name: 'Add dependency' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('would create the cycle orders → revenue job → exec report → orders');
  });
});
