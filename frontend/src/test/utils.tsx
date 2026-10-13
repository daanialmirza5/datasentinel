import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';

export interface RecordedCall {
  method: string;
  path: string;
  query: URLSearchParams;
  body: unknown;
}

type Handler = (call: RecordedCall) => { status?: number; body: unknown } | unknown;

/**
 * Stubs global fetch with a route table keyed by "METHOD /path" (query ignored). Handlers may
 * return a plain body or { status, body }. Unmatched requests fail the test loudly.
 */
export function mockApi(routes: Record<string, Handler>) {
  const calls: RecordedCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    const method = (init?.method ?? 'GET').toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, '');
    let body: unknown = undefined;
    if (init?.body instanceof FormData) body = init.body;
    else if (typeof init?.body === 'string') body = JSON.parse(init.body);
    const call = { method, path, query: url.searchParams, body };
    calls.push(call);
    const handler = routes[`${method} ${path}`];
    if (!handler) throw new Error(`Unmocked request: ${method} ${path}`);
    const result = handler(call) as { status?: number; body?: unknown } | undefined;
    const isEnvelope = result !== null && typeof result === 'object' && 'body' in result && ('status' in result);
    const status = isEnvelope ? (result.status ?? 200) : 200;
    const payload = isEnvelope ? result.body : result;
    return new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetchMock);
  return { calls, fetchMock };
}

export function apiError(status: number, code: string, message: string, details?: unknown) {
  return { status, body: { error: { code, message, details }, request_id: 'req123' } };
}

export function renderAt(element: ReactElement, path = '/', route = '*') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={route} element={element} />
      </Routes>
    </MemoryRouter>,
  );
}
