import { useState } from 'react';
import { api } from '../api/client';
import type { ColumnComparison, Dataset, Signal } from '../api/types';
import { ComparisonChart } from '../components/charts';
import { DatasetPicker } from '../components/DatasetPicker';
import { useDatasets, useSelectedDataset } from '../hooks/useDatasets';
import { Badge, Card, EmptyState, ErrorState, Loading, PageHeader, SeverityBadge } from '../components/ui';
import { formatNumber, inputClass } from '../lib/format';
import { useAsync } from '../hooks/useAsync';

export function DriftPage() {
  const datasets = useDatasets();
  const [selected, setSelected] = useSelectedDataset();
  const items = datasets.data?.items ?? [];
  const dataset = items.find((d) => d.id === selected);
  return (
    <>
      <PageHeader
        title="Drift monitoring"
        description="Version-to-version comparison: schema changes, statistical tests with effect-size floors, and an explanation for every signal."
        actions={items.length > 0 && <DatasetPicker datasets={items} value={selected} onChange={setSelected} />}
      />
      {datasets.loading && !datasets.data && <Loading />}
      {datasets.error && <ErrorState error={datasets.error} onRetry={datasets.reload} />}
      {datasets.data && items.length === 0 && <EmptyState title="No datasets">Import at least two versions of a dataset to compare them.</EmptyState>}
      {dataset && <DriftWorkspace key={dataset.id} dataset={dataset} />}
    </>
  );
}

function DriftWorkspace({ dataset }: { dataset: Dataset }) {
  const versions = useAsync(() => api.versions(dataset.id), [dataset.id]);
  const [base, setBase] = useState('');
  const [candidate, setCandidate] = useState('');
  const [onlyFlagged, setOnlyFlagged] = useState(true);
  const drift = useAsync(
    () => api.drift(dataset.id, { base_version_id: base || undefined, candidate_version_id: candidate || undefined }),
    [dataset.id, base, candidate],
  );

  const versionOptions = versions.data ?? [];
  const d = drift.data;
  const flaggedColumns = new Set((d?.signals ?? []).map((s) => s.column).filter(Boolean));
  const comparisons = (d?.column_comparisons ?? []).filter((c) => !onlyFlagged || flaggedColumns.has(c.column));

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex flex-col gap-1">
            <label htmlFor="base-version" className="text-xs font-medium text-ink-2">
              Baseline version
            </label>
            <select id="base-version" className={inputClass} value={base || d?.base?.id || ''} onChange={(e) => setBase(e.target.value)}>
              {!d?.base && <option value="">(previous active version)</option>}
              {versionOptions.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.version_number} — {v.original_filename}
                </option>
              ))}
            </select>
          </div>
          <span aria-hidden="true" className="pb-2 text-ink-3">→</span>
          <div className="flex flex-col gap-1">
            <label htmlFor="candidate-version" className="text-xs font-medium text-ink-2">
              Candidate version
            </label>
            <select id="candidate-version" className={inputClass} value={candidate || d?.candidate.id || ''} onChange={(e) => setCandidate(e.target.value)}>
              {versionOptions.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.version_number} — {v.original_filename}
                </option>
              ))}
            </select>
          </div>
          {d?.row_count && (
            <p className="tabular pb-2 text-sm text-ink-2">
              Rows {formatNumber(d.row_count.base)} → {formatNumber(d.row_count.candidate)}
              {d.row_count.change_pct !== null && ` (${d.row_count.change_pct > 0 ? '+' : ''}${formatNumber(d.row_count.change_pct)}%)`}
            </p>
          )}
        </div>
      </Card>

      {drift.loading && <Loading label="Comparing versions…" />}
      {drift.error && <ErrorState error={drift.error} onRetry={drift.reload} />}
      {d?.status === 'no_baseline' && <EmptyState title="Nothing to compare yet">{d.message}</EmptyState>}

      {d?.status === 'ok' && (
        <>
          <div className="grid gap-6 xl:grid-cols-2">
            <Card title={`Schema changes (${d.schema_changes?.length ?? 0})`}>
              {d.schema_changes?.length === 0 ? (
                <p className="text-sm text-ink-2">The schemas are identical.</p>
              ) : (
                <ul className="space-y-3 text-sm">
                  {d.schema_changes?.map((c, i) => (
                    <li key={i}>
                      <div className="flex flex-wrap items-center gap-2">
                        <SeverityBadge severity={c.severity} />
                        <span className="font-medium">{c.change_type.replace(/_/g, ' ')}</span>
                        <code className="text-xs">{c.column}</code>
                        {(c.from || c.to) && (
                          <span className="text-xs text-ink-3">
                            {c.from ?? '∅'} → {c.to ?? '∅'}
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-ink-2">{c.explanation}</p>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title={`Signals (${d.signals?.length ?? 0})`}>
              {d.signals?.length === 0 ? <p className="text-sm text-ink-2">No signals: no test exceeded both its significance level and effect-size floor.</p> : <SignalList signals={d.signals ?? []} />}
            </Card>
          </div>

          <Card
            title="Column comparisons"
            actions={
              <label className="flex items-center gap-2 text-sm text-ink-2">
                <input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} /> Only columns with signals
              </label>
            }
          >
            {comparisons.length === 0 && <p className="text-sm text-ink-2">No columns to show. Clear the filter to see every column.</p>}
            <div className="grid gap-6 xl:grid-cols-2">
              {comparisons.map((c) => (
                <ComparisonCard key={c.column} comparison={c} baseLabel={`v${d.base?.version_number}`} candidateLabel={`v${d.candidate.version_number}`} />
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

export function SignalList({ signals }: { signals: Signal[] }) {
  return (
    <ul className="divide-y divide-line">
      {signals.map((s, i) => (
        <li key={`${s.key}-${s.source}-${i}`} className="py-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={s.severity} />
            <span className="font-medium">{s.title}</span>
            <Badge>{s.source}</Badge>
          </div>
          <p className="mt-1 text-ink-2">{s.explanation}</p>
          <details className="mt-1 text-xs">
            <summary className="cursor-pointer text-ink-3">Evidence</summary>
            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-canvas p-2">{JSON.stringify(s.evidence, null, 2)}</pre>
          </details>
        </li>
      ))}
    </ul>
  );
}

function ComparisonCard({ comparison: c, baseLabel, candidateLabel }: { comparison: ColumnComparison; baseLabel: string; candidateLabel: string }) {
  const facts: string[] = [];
  if (c.base_type !== c.candidate_type) facts.push(`type ${c.base_type} → ${c.candidate_type}`);
  if (c.null_rate?.delta_pp !== undefined) facts.push(`missing ${formatNumber(c.null_rate.base_pct)}% → ${formatNumber(c.null_rate.candidate_pct)}%`);
  if (c.distribution?.ks_statistic !== undefined) facts.push(`KS D=${formatNumber(c.distribution.ks_statistic, 3)} (p=${c.distribution.p_value?.toExponential(1)})`);
  if (c.distribution?.psi !== undefined && c.distribution.psi !== null) facts.push(`PSI ${formatNumber(c.distribution.psi, 3)}`);
  if (c.categories?.psi !== undefined) facts.push(`category PSI ${formatNumber(c.categories.psi, 3)}`);
  if (c.categories?.new_values && Object.keys(c.categories.new_values).length) facts.push(`new values: ${Object.keys(c.categories.new_values).join(', ')}`);
  if (c.distribution?.status === 'skipped_identifier') facts.push('identifier — distribution not compared');
  if (c.distribution?.status === 'insufficient_sample') facts.push('too few values to test');
  return (
    <div className="min-w-0 rounded-lg border border-line p-4">
      <p className="mb-1 font-medium">
        <code>{c.column}</code> <span className="text-xs font-normal text-ink-3">{c.base_type}</span>
      </p>
      <p className="mb-2 text-xs text-ink-2">{facts.join(' · ') || 'No notable differences.'}</p>
      {c.chart && <ComparisonChart chart={c.chart} label={`Distribution of ${c.column}: ${baseLabel} vs ${candidateLabel}`} baseLabel={baseLabel} candidateLabel={candidateLabel} />}
    </div>
  );
}
