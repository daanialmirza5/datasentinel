import type {
  AnomalyResponse,
  AssetDetails,
  Dashboard,
  Dataset,
  DriftResponse,
  Experiment,
  FaultType,
  HealthResponse,
  ImpactResponse,
  ImportResponse,
  LineageGraph,
  Page,
  Preview,
  ProfileResponse,
  ReadyResponse,
  RejectedRow,
  Report,
  ReportSummary,
  Rule,
  RuleInput,
  RuleTypeInfo,
  SettingsInfo,
  ValidationRun,
  Version,
} from './types';

const BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, details?: unknown, requestId?: string | null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId ?? null;
  }
}

/** Escapes an id for use as one URL path segment. */
const enc = encodeURIComponent;

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  const qs = params.toString();
  return `${BASE}/api/v1${path}${qs ? `?${qs}` : ''}`;
}

async function parseError(response: Response): Promise<ApiError> {
  let body: { error?: { code?: string; message?: string; details?: unknown }; request_id?: string } = {};
  try {
    body = await response.json();
  } catch {
    // non-JSON error (proxy, network appliance) — fall through to a generic message
  }
  const message = body.error?.message ?? `Request failed with status ${response.status}`;
  return new ApiError(response.status, body.error?.code ?? 'http_error', message, body.error?.details, body.request_id);
}

export async function request<T>(method: string, path: string, options: { query?: Query; body?: unknown; form?: FormData } = {}): Promise<T> {
  const init: RequestInit = { method, headers: { Accept: 'application/json' } };
  if (options.form) {
    init.body = options.form;
  } else if (options.body !== undefined) {
    init.body = JSON.stringify(options.body);
    (init.headers as Record<string, string>)['Content-Type'] = 'application/json';
  }
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), init);
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the DataSentinel API. Is the backend running?');
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function exportUrl(reportId: string, format: 'json' | 'markdown'): string {
  return buildUrl(`/reports/${enc(reportId)}/export`, { format });
}

export const api = {
  health: () => request<HealthResponse>('GET', '/health'),
  ready: () => request<ReadyResponse>('GET', '/ready'),
  dashboard: () => request<Dashboard>('GET', '/dashboard'),
  settings: () => request<SettingsInfo>('GET', '/settings'),
  loadSamples: () => request<{ datasets: number; versions: number; rules: number }>('POST', '/samples/load'),
  runIntegrity: () =>
    request<{ ok: boolean; database: { ok: boolean }; files: { checked: number; missing: unknown[]; corrupted: unknown[]; orphaned: string[] } }>('POST', '/maintenance/integrity'),
  runRetention: () => request<{ expired_experiments_removed: number }>('POST', '/maintenance/retention'),

  datasets: (query?: Query) => request<Page<Dataset>>('GET', '/datasets', { query }),
  dataset: (id: string) => request<Dataset>('GET', `/datasets/${enc(id)}`),
  deleteDataset: (id: string) => request<{ deleted: boolean }>('DELETE', `/datasets/${enc(id)}`),
  importDataset: (form: FormData) => request<ImportResponse>('POST', '/datasets/import', { form }),
  versions: (id: string) => request<Version[]>('GET', `/datasets/${enc(id)}/versions`),
  quarantine: (id: string, versionId: string, reason: string) =>
    request<Version>('POST', `/datasets/${enc(id)}/versions/${enc(versionId)}/quarantine`, { body: { reason } }),
  release: (id: string, versionId: string) => request<Version>('POST', `/datasets/${enc(id)}/versions/${enc(versionId)}/release`),
  preview: (id: string, query: Query) => request<Preview>('GET', `/datasets/${enc(id)}/preview`, { query }),
  rejectedRows: (id: string, versionId?: string) =>
    request<{ total: number; truncated: boolean; rows: RejectedRow[] }>('GET', `/datasets/${enc(id)}/rejected-rows`, { query: { version_id: versionId } }),
  profile: (id: string, versionId?: string) => request<ProfileResponse>('GET', `/datasets/${enc(id)}/profile`, { query: { version_id: versionId } }),
  drift: (id: string, query?: Query) => request<DriftResponse>('GET', `/datasets/${enc(id)}/drift`, { query }),
  anomalies: (id: string, query?: Query) => request<AnomalyResponse>('GET', `/datasets/${enc(id)}/anomalies`, { query }),

  ruleTypes: () => request<{ severities: string[]; types: RuleTypeInfo[] }>('GET', '/rule-types'),
  rules: (datasetId: string) => request<Rule[]>('GET', `/datasets/${enc(datasetId)}/rules`),
  createRule: (datasetId: string, body: RuleInput) => request<Rule>('POST', `/datasets/${enc(datasetId)}/rules`, { body }),
  updateRule: (ruleId: string, body: Partial<RuleInput>) => request<Rule>('PATCH', `/rules/${enc(ruleId)}`, { body }),
  deleteRule: (ruleId: string) => request<{ deleted: boolean }>('DELETE', `/rules/${enc(ruleId)}`),
  suggestions: (datasetId: string) =>
    request<{ suggestions: (RuleInput & { reason: string })[] }>('GET', `/datasets/${enc(datasetId)}/rules/suggestions`),
  validate: (datasetId: string, body: { version_id?: string; rule_ids?: string[] } = {}) =>
    request<ValidationRun>('POST', `/datasets/${enc(datasetId)}/validate`, { body }),
  validations: (datasetId: string, query?: Query) => request<ValidationRun[]>('GET', `/datasets/${enc(datasetId)}/validations`, { query }),
  validation: (runId: string) => request<ValidationRun>('GET', `/validations/${enc(runId)}`),

  lineage: () => request<LineageGraph>('GET', '/lineage'),
  asset: (id: string) => request<AssetDetails>('GET', `/lineage/${enc(id)}`),
  impact: (id: string) => request<ImpactResponse>('GET', `/lineage/${enc(id)}/impact`),
  createAsset: (body: { name: string; kind: string; description?: string; owner?: string }) =>
    request<{ id: string }>('POST', '/lineage/assets', { body }),
  deleteAsset: (id: string) => request<{ deleted: boolean }>('DELETE', `/lineage/assets/${enc(id)}`),
  createEdge: (body: { source_id: string; target_id: string; description?: string }) =>
    request<{ id: string }>('POST', '/lineage/edges', { body }),
  deleteEdge: (id: string) => request<{ deleted: boolean }>('DELETE', `/lineage/edges/${enc(id)}`),

  faultTypes: (datasetId?: string) => request<{ fault_types: FaultType[] }>('GET', '/experiments/fault-types', { query: { dataset_id: datasetId } }),
  experiments: (query?: Query) => request<Page<Experiment>>('GET', '/experiments', { query }),
  experiment: (id: string) => request<Experiment>('GET', `/experiments/${enc(id)}`),
  createExperiment: (body: { dataset_id: string; version_id?: string; fault_type: string; params: Record<string, unknown>; seed: number }) =>
    request<Experiment>('POST', '/experiments', { body }),
  regenerateExperiment: (id: string, seed?: number) =>
    request<Experiment>('POST', `/experiments/${enc(id)}/regenerate`, { body: seed === undefined ? {} : { seed } }),
  deleteExperiment: (id: string) => request<{ deleted: boolean }>('DELETE', `/experiments/${enc(id)}`),

  reports: () => request<Page<ReportSummary>>('GET', '/reports'),
  report: (id: string) => request<Report>('GET', `/reports/${enc(id)}`),
  createReport: (body: { dataset_id?: string; experiment_id?: string; title?: string }) => request<Report>('POST', '/reports', { body }),
  deleteReport: (id: string) => request<{ deleted: boolean }>('DELETE', `/reports/${enc(id)}`),
};
