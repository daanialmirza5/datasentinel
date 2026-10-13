export type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical';
export type RuleStatus = 'passed' | 'failed' | 'error' | 'not_evaluated';
export type Health = 'passing' | 'failing' | 'incomplete' | 'no_rules';
export type AssetState = 'failing' | 'anomalous' | 'passing' | 'unvalidated' | 'no_checks';
export type ImpactClass = 'confirmed_failure' | 'suspected_impact' | 'unverified_risk' | 'no_known_impact';

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ColumnSchema {
  name: string;
  type: string;
  nullable: boolean;
  invalid_count: number;
  datetime_format: string | null;
  mixed: boolean;
}

export interface Version {
  id: string;
  dataset_id: string;
  version_number: number;
  origin: string;
  original_filename: string;
  file_format: string;
  size_bytes: number;
  sha256: string;
  row_count: number;
  column_count: number;
  rejected_row_count: number;
  duplicate_row_count: number;
  status: 'active' | 'quarantined';
  status_reason: string;
  imported_at: string;
  parent_version_id: string | null;
  schema: ColumnSchema[];
}

export interface Dataset {
  id: string;
  name: string;
  description: string;
  kind: 'user' | 'sample' | 'lab';
  created_at: string;
  updated_at: string;
  version_count: number;
  current_version: Version | null;
  asset_id: string | null;
}

export interface ImportSummary {
  file_format: string;
  encoding: string;
  delimiter: string | null;
  rows_accepted: number;
  rows_rejected: number;
  blank_lines_skipped: number;
  duplicate_rows: number;
  columns: number;
  type_counts: Record<string, number>;
  missing_cells: number;
  invalid_cells: number;
  warnings: string[];
  rejected_rows: RejectedRow[];
}

export interface RejectedRow {
  line: number;
  reason: string;
  preview: string;
}

export interface ImportResponse {
  dataset: Dataset;
  version: Version;
  summary: ImportSummary;
}

export interface Preview {
  dataset_id: string;
  version_id: string;
  columns: ColumnSchema[];
  rows: (string | null)[][];
  row_numbers: number[];
  total: number;
  offset: number;
  limit: number;
}

export interface Histogram {
  kind: 'bins' | 'discrete' | 'time_bins';
  edges?: (number | string)[];
  values?: number[];
  counts: number[];
}

export interface FrequencyItem {
  value: string;
  count: number;
  pct: number;
}

export interface ColumnProfile {
  name: string;
  type: string;
  non_null_count: number;
  null_count: number;
  null_pct: number;
  distinct_count: number;
  distinct_pct: number;
  unique: boolean;
  duplicate_value_count: number;
  invalid_count: number;
  invalid_pct: number;
  invalid_examples: string[];
  is_constant: boolean;
  is_categorical: boolean;
  mixed: boolean;
  notes: string[];
  top_values: FrequencyItem[];
  categories?: FrequencyItem[];
  min?: number | string;
  max?: number | string;
  mean?: number;
  median?: number;
  std?: number | null;
  quantiles?: Record<string, number>;
  outliers?: { iqr_count: number | null; mad_count: number | null };
  histogram?: Histogram | null;
  length?: { min: number; max: number; mean: number };
  true_count?: number;
  false_count?: number;
  range_days?: number;
  future_count?: number;
}

export interface Profile {
  row_count: number;
  column_count: number;
  duplicate_rows: number;
  duplicate_pct: number;
  missing_cells: number;
  missing_pct: number;
  exact: boolean;
  notes: string[];
  columns: ColumnProfile[];
}

export interface ProfileResponse {
  dataset_id: string;
  version_id: string;
  version_number: number;
  computed_at: string;
  duration_ms: number;
  cached: boolean;
  profile: Profile;
}

export interface Rule {
  id: string;
  dataset_id: string;
  name: string;
  rule_type: string;
  column_name: string | null;
  params: Record<string, unknown>;
  severity: Severity;
  enabled: boolean;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface RuleInput {
  name: string;
  rule_type: string;
  column_name: string | null;
  params: Record<string, unknown>;
  severity: Severity;
  enabled?: boolean;
  description?: string;
}

export interface RuleTypeInfo {
  rule_type: string;
  label: string;
  description: string;
  requires_column: boolean;
  scope: string;
  params_schema: { properties?: Record<string, { type?: string; default?: unknown; description?: string }> };
}

export interface RuleResult {
  id: string;
  rule_id: string | null;
  rule_name: string;
  rule_type: string;
  column_name: string | null;
  severity: Severity;
  status: RuleStatus;
  evaluated_count: number;
  violation_count: number;
  violation_pct: number;
  message: string;
  recommendation: string;
  examples: { row: number; values: Record<string, string | null> }[];
  details: Record<string, unknown>;
}

export interface ValidationSummary {
  total: number;
  passed: number;
  failed: number;
  error: number;
  not_evaluated: number;
  health: Health;
}

export interface ValidationRun {
  id: string;
  dataset_id: string;
  version_id: string;
  version_number: number | null;
  trigger: string;
  started_at: string;
  finished_at: string | null;
  summary: ValidationSummary;
  results: RuleResult[] | null;
}

export interface Signal {
  key: string;
  category: string;
  label: string;
  severity: Severity;
  title: string;
  explanation: string;
  column: string | null;
  source: string;
  evidence: Record<string, unknown>;
}

export interface SchemaChange {
  change_type: string;
  column: string;
  from: string | null;
  to: string | null;
  severity: Severity;
  explanation: string;
}

export interface ComparisonChart {
  kind: 'numeric' | 'categorical';
  binning?: 'baseline_quantiles_with_tails';
  edges?: number[];
  labels?: string[];
  base: number[];
  candidate: number[];
}

export interface ColumnComparison {
  column: string;
  base_type: string;
  candidate_type: string;
  identifier: boolean;
  base_null_pct: number | null;
  candidate_null_pct: number | null;
  null_rate?: { base_pct?: number; candidate_pct?: number; delta_pp?: number; p_value?: number; status?: string };
  distribution?: { ks_statistic?: number; p_value?: number; psi?: number | null; status?: string; reason?: string };
  categories?: { new_values?: Record<string, number>; psi?: number; chi2_p_value?: number; status?: string };
  chart?: ComparisonChart;
}

export interface VersionRef {
  id: string;
  version_number: number;
  imported_at: string;
  row_count: number;
  status: string;
}

export interface DriftResponse {
  status: 'ok' | 'no_baseline';
  message?: string;
  dataset_id: string;
  base?: VersionRef;
  candidate: VersionRef;
  row_count?: { base: number; candidate: number; change_pct: number | null };
  schema_changes?: SchemaChange[];
  column_comparisons?: ColumnComparison[];
  signals?: Signal[];
  summary?: { signal_count: number; actionable_signal_count: number; max_severity: Severity | null };
}

export interface AnomalyResponse {
  dataset_id: string;
  version: VersionRef;
  outliers: { column: string; method: string; count: number; pct: number; examples: { row: number; value: string; score: number }[] }[];
  outliers_not_applicable: { column: string; method: string; flagged_pct: number; reason: string }[];
  time_series: {
    column: string;
    days: number;
    metrics_checked: string[];
    deviations: { date: string; metric: string; value: number; median: number; robust_z: number }[];
    series: Record<string, { date: string; value: number | null }[]>;
    skipped?: string;
  } | null;
  ml: { available: boolean; ran?: boolean; reason?: string; outlier_count?: number; top_rows?: { row: number; score: number; values: Record<string, string | null> }[] } | null;
  signals: Signal[];
}

export interface LineageNode {
  id: string;
  name: string;
  kind: string;
  description: string;
  owner: string;
  dataset_id: string | null;
  position: { x: number; y: number };
  health: { state: AssetState; version_number?: number | null; failed_rule_count: number; signal_count: number };
  upstream_count: number;
  downstream_count: number;
}

export interface LineageGraph {
  nodes: LineageNode[];
  edges: { id: string; source: string; target: string; description: string }[];
  cycles: string[][];
}

export interface Dependency {
  id: string;
  name: string;
  kind: string;
  distance: number;
  path: string[];
}

export interface AssetHealth {
  state: AssetState;
  version_number?: number;
  failed_rules?: { rule_name: string; severity: Severity; violation_count: number; message: string }[];
  breaking_changes?: Signal[];
  anomaly_signals?: Signal[];
  schema_changes?: SchemaChange[];
  reason?: string;
}

export interface AssetDetails {
  id: string;
  name: string;
  kind: string;
  description: string;
  owner: string;
  dataset_id: string | null;
  health: AssetHealth;
  upstream: Dependency[];
  downstream: Dependency[];
  versions: { id: string; version_number: number; row_count: number; status: string; imported_at: string }[];
}

export interface ImpactedAsset {
  id: string;
  name: string;
  kind: string;
  owner?: string;
  distance: number;
  path: string[];
  path_ids: string[];
  classification: ImpactClass;
  own_state?: AssetState;
  evidence?: string[];
}

export interface Recommendation {
  priority: number;
  kind: 'contain' | 'investigate' | 'recover' | 'verify' | 'prevent';
  title: string;
  rationale: string;
  evidence: string[];
  action?: { type: string; dataset_id: string; version_id: string };
}

export interface ImpactResponse {
  origin: { id: string; name: string; health: AssetHealth };
  origin_state: AssetState;
  assessment: string;
  direct: ImpactedAsset[];
  transitive: ImpactedAsset[];
  impacted: ImpactedAsset[];
  counts: Record<ImpactClass, number>;
  restore_candidate: { version_number: number; evidence: string } | null;
  recommendations: Recommendation[];
}

export interface FaultType {
  fault_type: string;
  label: string;
  description: string;
  column_kind: string | null;
  expected_signals: string[];
  note: string;
  eligible_columns?: string[];
  params_schema: { properties?: Record<string, { type?: string; default?: unknown; description?: string; enum?: string[] }> };
}

export interface BriefSignal {
  key: string;
  category: string;
  column: string | null;
  severity: Severity;
  title: string;
  source?: string;
}

export interface Experiment {
  id: string;
  dataset_id: string;
  dataset_name: string | null;
  base_version_id: string;
  base_version_number: number | null;
  lab_dataset_id: string | null;
  result_version_id: string | null;
  fault_type: string;
  params: Record<string, unknown>;
  seed: number;
  status: string;
  duration_ms: number;
  created_at: string;
  expires_at: string | null;
  outcome: 'detected' | 'partially_detected' | 'missed' | null;
  detected: boolean | null;
  counts: Record<string, number> | null;
  ground_truth?: {
    scope: string;
    affected_columns: string[];
    affected_rows: number;
    expected: { primary: string[]; accepted: string[] };
    examples: { row?: number; before?: Record<string, string | null>; after?: Record<string, string | null>; note?: string }[];
  };
  detection?: { signals: Signal[]; schema_changes: SchemaChange[]; column_comparisons: ColumnComparison[]; row_count: { base: number; candidate: number } };
  evaluation?: {
    outcome: string;
    detected: boolean;
    expected_signals: { category: string; column: string | null }[];
    matched_signals: { category: string; column: string | null }[];
    missed_signals: { category: string; column: string | null }[];
    true_positives: BriefSignal[];
    false_positives: BriefSignal[];
    signal_precision: number | null;
    modified_sha256: string;
    base_rows: number;
    modified_rows: number;
    simulated_impact: { simulated_origin_state: string; impacted: ImpactedAsset[] };
  };
}

export interface ReportSummary {
  id: string;
  title: string;
  kind: 'dataset' | 'experiment';
  dataset_id: string | null;
  version_id: string | null;
  created_at: string;
}

export interface Report extends ReportSummary {
  content: Record<string, unknown> & {
    title: string;
    generated_at: string;
    recommendations?: Recommendation[];
    drift?: { status: string; signals?: Signal[]; schema_changes?: SchemaChange[]; message?: string };
    quality?: { status: string; summary?: ValidationSummary; results?: RuleResult[]; message?: string };
    impact?: { origin_state: string; assessment: string; impacted: ImpactedAsset[] } | null;
    evaluation?: Experiment['evaluation'];
  };
}

export interface Dashboard {
  dataset_count: number;
  version_count: number;
  rule_count: number;
  report_count: number;
  experiment_count: number;
  recent_imports: {
    dataset_id: string;
    dataset_name: string;
    version_id: string;
    version_number: number;
    row_count: number;
    origin: string;
    rejected_row_count: number;
    imported_at: string;
    status: string;
  }[];
  rule_status: { passed: number; failed: number; error: number; not_evaluated: number; datasets_failing: number };
  active_anomalies: { count: number; items: (Signal & { dataset_id: string; dataset_name: string; version_number: number })[] };
  schema_changes: { count: number; items: (SchemaChange & { dataset_id: string; dataset_name: string; version_number: number })[] };
  impact: { origins: { id: string; name: string; state: string; impacted: number }[]; impacted: { id: string; name: string; kind: string; classification: ImpactClass; via: string }[]; counts: Record<ImpactClass, number> };
  datasets: { dataset_id: string; name: string; kind: string; version_number: number; row_count: number; health: Health; failed_rules: number; signals: number; imported_at: string }[];
}

export interface SettingsInfo {
  version: string;
  environment: string;
  demo_mode: boolean;
  database_backend: string;
  storage: { usage_bytes: number; location: string };
  limits: Record<string, number>;
  retention: { user_data: string; lab_data_hours: number; lab_data: string };
  privacy: { external_services: string[]; statement: string };
  cors_origins: string[];
  ml_detector_available: boolean;
  detection_config: Record<string, number>;
}

export interface HealthResponse {
  status: string;
  version: string;
}

export interface ReadyResponse {
  status: 'ready' | 'not_ready';
  checks: Record<string, { ok: boolean; [key: string]: unknown }>;
}
