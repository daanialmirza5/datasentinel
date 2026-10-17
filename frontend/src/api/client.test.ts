import { describe, expect, it, vi } from 'vitest';
import { apiError, mockApi } from '../test/utils';
import { api, ApiError, exportUrl } from './client';

describe('api client', () => {
  it('builds versioned URLs with query strings and skips empty values', async () => {
    const { calls } = mockApi({ 'GET /datasets': () => ({ items: [], total: 0, limit: 5, offset: 0 }) });
    await api.datasets({ q: 'ord', limit: 5, kind: undefined });
    expect(calls[0]?.query.get('q')).toBe('ord');
    expect(calls[0]?.query.has('kind')).toBe(false);
  });

  it('turns the error envelope into an ApiError with code, details and request id', async () => {
    mockApi({ 'GET /datasets/ds_x': () => apiError(404, 'not_found', "Dataset 'ds_x' not found") });
    const error = await api.dataset('ds_x').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, code: 'not_found', message: "Dataset 'ds_x' not found", requestId: 'req123' });
  });

  it('reports network failures honestly', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(api.health()).rejects.toMatchObject({ code: 'network_error', status: 0 });
  });

  it('sends JSON bodies with a content type', async () => {
    const { calls, fetchMock } = mockApi({ 'POST /reports': () => ({ id: 'rpt_1' }) });
    await api.createReport({ dataset_id: 'ds_1' });
    expect(calls[0]?.body).toEqual({ dataset_id: 'ds_1' });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('escapes ids used as path segments', () => {
    expect(exportUrl('rpt/../x', 'json')).toBe('/api/v1/reports/rpt%2F..%2Fx/export?format=json');
  });

  it('exposes report export URLs', () => {
    expect(exportUrl('rpt_1', 'markdown')).toBe('/api/v1/reports/rpt_1/export?format=markdown');
  });
});
