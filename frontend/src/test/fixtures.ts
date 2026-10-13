import type { Dataset, Version } from '../api/types';

export const version = (overrides: Partial<Version> = {}): Version => ({
  id: 'ver_1',
  dataset_id: 'ds_orders',
  version_number: 1,
  origin: 'upload',
  original_filename: 'orders.csv',
  file_format: 'csv',
  size_bytes: 2048,
  sha256: 'a'.repeat(64),
  row_count: 120,
  column_count: 3,
  rejected_row_count: 0,
  duplicate_row_count: 0,
  status: 'active',
  status_reason: '',
  imported_at: '2026-10-01T10:00:00Z',
  parent_version_id: null,
  schema: [
    { name: 'order_id', type: 'integer', nullable: true, invalid_count: 0, datetime_format: null, mixed: false },
    { name: 'amount', type: 'float', nullable: true, invalid_count: 0, datetime_format: null, mixed: false },
    { name: 'status', type: 'string', nullable: true, invalid_count: 0, datetime_format: null, mixed: false },
  ],
  ...overrides,
});

export const dataset = (overrides: Partial<Dataset> = {}): Dataset => ({
  id: 'ds_orders',
  name: 'orders',
  description: 'Order exports',
  kind: 'user',
  created_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-01T10:00:00Z',
  version_count: 1,
  current_version: version(),
  asset_id: 'asset_orders',
  ...overrides,
});

export const page = <T>(items: T[]) => ({ items, total: items.length, limit: 200, offset: 0 });
