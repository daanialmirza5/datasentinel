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
  return (await response.json()) as T;
}

export function exportUrl(reportId: string, format: 'json' | 'markdown'): string {
  return buildUrl(`/reports/${reportId}/export`, { format });
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
  dataset: (id: string) => request<Dataset>('GET', `/datasets/${id}`),
  deleteDataset: (id: string) => request<{ deleted: boolean }>('DELETE', `/datasets/${id}`),
  importDataset: (form: FormData) => request<ImportResponse>('POST', '/datasets/import', { form }),
  versions: (id: string) => request<Version[]>('GET', `/datasets/${id}/versions`),
  quarantine: (id: string, versionId: string, reason: string) =>
    request<Version>('POST', `/datasets/${id}/versions/${versionId}/quarantine`, { body: { reason } }),
  release: (id: string, versionId: string) => request<Version>('POST', `/datasets/${id}/versions/${versionId}/release`),
  preview: (id: string, query: Query) => request<Preview>('GET', `/datasets/${id}/preview`, { query }),
  rejectedRows: (id: string, versionId?: string) =>
    request<{ total: number; truncated: boolean; rows: RejectedRow[] }>('GET', `/datasets/${id}/rejected-rows`, { query: { version_id: versionId } }),
  profile: (id: string, versionId?: string) => request<ProfileResponse>('GET', `/datasets/${id}/profile`, { query: { version_id: versionId } }),
  drift: (id: string, query?: Query) => request<DriftResponse>('GET', `/datasets/${id}/drift`, { query }),
  anomalies: (id: string, query?: Query) => request<AnomalyResponse>('GET', `/datasets/${id}/anomalies`, { query }),

  ruleTypes: () => request<{ severities: string[]; types: RuleTypeInfo[] }>('GET', '/rule-types'),
  rules: (datasetId: string) => request<Rule[]>('GET', `/datasets/${datasetId}/rules`),
  createRule: (datasetId: string, body: RuleInput) => request<Rule>('POST', `/datasets/${datasetId}/rules`, { body }),
  updateRule: (ruleId: string, body: Partial<RuleInput>) => request<Rule>('PATCH', `/rules/${ruleId}`, { body }),
  deleteRule: (ruleId: string) => request<{ deleted: boolean }>('DELETE', `/rules/${ruleId}`),
  suggestions: (datasetId: string) =>
    request<{ suggestions: (RuleInput & { reason: string })[] }>('GET', `/datasets/${datasetId}/rules/suggestions`),
  validate: (datasetId: string, body: { version_id?: string; rule_ids?: string[] } = {}) =>
    request<ValidationRun>('POST', `/datasets/${datasetId}/validate`, { body }),
  validations: (datasetId: string, query?: Query) => request<ValidationRun[]>('GET', `/datasets/${datasetId}/validations`, { query }),
  validation: (runId: string) => request<ValidationRun>('GET', `/validations/${runId}`),

  lineage: () => request<LineageGraph>('GET', '/lineage'),
  asset: (id: string) => request<AssetDetails>('GET', `/lineage/${id}`),
  impact: (id: string) => request<ImpactResponse>('GET', `/lineage/${id}/impact`),
  createAsset: (body: { name: string; kind: string; description?: string; owner?: string }) =>
    request<{ id: string }>('POST', '/lineage/assets', { body }),
  deleteAsset: (id: string) => request<{ deleted: boolean }>('DELETE', `/lineage/assets/${id}`),
  createEdge: (body: { source_id: string; target_id: string; description?: string }) =>
    request<{ id: string }>('POST', '/lineage/edges', { body }),
  deleteEdge: (id: string) => request<{ deleted: boolean }>('DELETE', `/lineage/edges/${id}`),

  faultTypes: (datasetId?: string) => request<{ fault_types: FaultType[] }>('GET', '/experiments/fault-types', { query: { dataset_id: datasetId } }),
  experiments: (query?: Query) => request<Page<Experiment>>('GET', '/experiments', { query }),
  experiment: (id: string) => request<Experiment>('GET', `/experiments/${id}`),
  createExperiment: (body: { dataset_id: string; fault_type: string; params: Record<string, unknown>; seed: number }) =>
    request<Experiment>('POST', '/experiments', { body }),
  regenerateExperiment: (id: string, seed?: number) =>
    request<Experiment>('POST', `/experiments/${id}/regenerate`, { body: seed === undefined ? {} : { seed } }),
  deleteExperiment: (id: string) => request<{ deleted: boolean }>('DELETE', `/experiments/${id}`),

  reports: () => request<Page<ReportSummary>>('GET', '/reports'),
  report: (id: string) => request<Report>('GET', `/reports/${id}`),
  createReport: (body: { dataset_id?: string; experiment_id?: string; title?: string }) => request<Report>('POST', '/reports', { body }),
  deleteReport: (id: string) => request<{ deleted: boolean }>('DELETE', `/reports/${id}`),
};
