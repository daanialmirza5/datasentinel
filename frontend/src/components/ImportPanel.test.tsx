import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { dataset, version } from '../test/fixtures';
import { apiError, mockApi } from '../test/utils';
import { ImportPanel } from './ImportPanel';

const summary = {
  file_format: 'csv', encoding: 'utf-8', delimiter: ',', rows_accepted: 120, rows_rejected: 1, blank_lines_skipped: 0,
  duplicate_rows: 2, columns: 3, type_counts: { integer: 1, float: 1, string: 1 }, missing_cells: 4, invalid_cells: 0,
  warnings: ["Duplicate column name 'a' renamed to 'a__2'."], rejected_rows: [{ line: 7, reason: 'Expected 3 fields, found 2', preview: '1,2' }],
};

describe('ImportPanel', () => {
  it('uploads a new dataset and shows the import summary with rejected rows', async () => {
    const onImported = vi.fn();
    const { calls } = mockApi({ 'POST /datasets/import': () => ({ dataset: dataset(), version: version(), summary }) });
    render(<ImportPanel datasets={[]} onImported={onImported} />);
    await userEvent.upload(screen.getByLabelText('File'), new File(['a,b\n1,2\n'], 'orders.csv', { type: 'text/csv' }));
    await userEvent.type(screen.getByLabelText('Dataset name (optional)'), 'orders');
    await userEvent.click(screen.getByRole('button', { name: 'Import' }));

    expect(await screen.findByText(/Imported orders version 1: 120 rows × 3 columns/)).toBeInTheDocument();
    expect(screen.getByText('1 rejected rows')).toBeInTheDocument();
    expect(screen.getByText(/line 7: Expected 3 fields, found 2/)).toBeInTheDocument();
    expect(screen.getByText("Duplicate column name 'a' renamed to 'a__2'.")).toBeInTheDocument();
    const form = calls[0]?.body as FormData;
    expect((form.get('file') as File).name).toBe('orders.csv');
    expect(form.get('dataset_name')).toBe('orders');
    expect(onImported).toHaveBeenCalledOnce();
  });

  it('imports as a new version of an existing dataset', async () => {
    const { calls } = mockApi({ 'POST /datasets/import': () => ({ dataset: dataset(), version: version({ version_number: 2 }), summary }) });
    render(<ImportPanel datasets={[dataset()]} onImported={() => {}} />);
    await userEvent.upload(screen.getByLabelText('File'), new File(['x'], 'orders.csv'));
    await userEvent.selectOptions(screen.getByLabelText('Import as'), 'ds_orders');
    expect(screen.queryByLabelText('Dataset name (optional)')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Import' }));
    await screen.findByText(/version 2/);
    expect((calls[0]?.body as FormData).get('dataset_id')).toBe('ds_orders');
  });

  it('shows validation feedback from the server', async () => {
    mockApi({ 'POST /datasets/import': () => apiError(422, 'validation_failed', 'Malformed JSON: Expecting value') });
    render(<ImportPanel datasets={[]} onImported={() => {}} />);
    await userEvent.upload(screen.getByLabelText('File'), new File(['{bad'], 'x.json'));
    await userEvent.click(screen.getByRole('button', { name: 'Import' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Malformed JSON: Expecting value');
  });

  it('requires a file before calling the API', async () => {
    const { calls } = mockApi({});
    render(<ImportPanel datasets={[]} onImported={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: 'Import' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a CSV, JSON or JSON Lines file first.');
    expect(calls).toHaveLength(0);
  });
});
