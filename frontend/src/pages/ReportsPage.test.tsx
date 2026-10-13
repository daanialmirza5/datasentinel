import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { dataset, page } from '../test/fixtures';
import { apiError, mockApi, renderAt } from '../test/utils';
import { ReportsPage } from './ReportsPage';

const report = {
  id: 'rpt_1', title: 'Data quality investigation: orders v3', kind: 'dataset', dataset_id: 'ds_orders', version_id: 'ver_3', created_at: '2026-10-01T10:00:00Z',
  content: {
    title: 'Data quality investigation: orders v3', generated_at: '2026-10-01T10:00:00Z', generator: 'DataSentinel 0.1.0', disclaimer: 'Signals are evidence, not proof.',
    quality: { status: 'evaluated', summary: { total: 2, passed: 1, failed: 1, error: 0, not_evaluated: 0, health: 'failing' }, results: [{ rule_name: 'currency values', status: 'failed', violation_count: 102, message: '102 not allowed' }] },
    drift: { status: 'compared', schema_changes: [], signals: [{ key: 'k', source: 'statistics', severity: 'medium', title: "Unexpected values in 'currency'" }] },
    anomalies: { signals: [] },
    impact: { origin_state: 'failing', assessment: "'orders' has confirmed failures.", impacted: [{ name: 'exec report', classification: 'unverified_risk', path: ['orders', 'exec report'] }] },
    recommendations: [{ priority: 1, kind: 'contain', title: "Quarantine version 3 of 'orders'", rationale: 'High severity', evidence: [] }],
  },
};

describe('ReportsPage', () => {
  it('generates a report and offers Markdown and JSON export', async () => {
    let created = false;
    const { calls } = mockApi({
      'GET /reports': () => page(created ? [report] : []),
      'GET /datasets': () => page([dataset()]),
      'POST /reports': () => {
        created = true;
        return report;
      },
      'GET /reports/rpt_1': () => report,
    });
    renderAt(<ReportsPage />, '/reports');
    await screen.findByText('No reports yet.');
    await userEvent.click(screen.getByRole('button', { name: 'Generate report' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ dataset_id: 'ds_orders' }));

    expect(await screen.findByText('102 not allowed', { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Quarantine version 3 of 'orders'")).toBeInTheDocument();
    expect(screen.getByText("'orders' has confirmed failures.")).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Export Markdown' })).toHaveAttribute('href', '/api/v1/reports/rpt_1/export?format=markdown');
    expect(screen.getByRole('link', { name: 'Export JSON' })).toHaveAttribute('href', '/api/v1/reports/rpt_1/export?format=json');
  });

  it('reports a missing report honestly', async () => {
    mockApi({
      'GET /reports': () => page([]),
      'GET /datasets': () => page([dataset()]),
      'GET /reports/rpt_gone': () => apiError(404, 'not_found', "Report 'rpt_gone' not found"),
    });
    renderAt(<ReportsPage />, '/reports?report=rpt_gone');
    expect(await screen.findByRole('alert')).toHaveTextContent("Report 'rpt_gone' not found");
  });
});
