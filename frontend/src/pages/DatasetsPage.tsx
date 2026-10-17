import { useState } from 'react';
import { api } from '../api/client';
import type { ColumnProfile, Dataset, Version } from '../api/types';
import { DistributionChart, FrequencyChart, TimeSeriesChart } from '../components/charts';
import { useDatasets, useSelectedDataset } from '../hooks/useDatasets';
import { ImportPanel } from '../components/ImportPanel';
import { Badge, Button, Card, EmptyState, ErrorState, KeyValue, Loading, PageHeader, Pagination, RuleStatusBadge, SeverityBadge, Tabs } from '../components/ui';
import { cx, formatBytes, formatDate, formatNumber, formatPercent, inputClass } from '../lib/format';
import { useAsync } from '../hooks/useAsync';

type Tab = 'versions' | 'preview' | 'profile' | 'quality' | 'anomalies';

export function DatasetsPage() {
  const datasets = useDatasets();
  const [selected, setSelected] = useSelectedDataset();
  const [showImport, setShowImport] = useState(false);
  const items = datasets.data?.items ?? [];
  const current = items.find((d) => d.id === selected) ?? items[0];

  return (
    <>
      <PageHeader
        title="Dataset explorer"
        description="Versions, parsed rows, exact column profiles, quality results and anomalies for every imported dataset."
        actions={
          <Button variant="primary" onClick={() => setShowImport((v) => !v)} aria-expanded={showImport}>
            {showImport ? 'Close import' : 'Import data'}
          </Button>
        }
      />
      {showImport && (
        <Card title="Import a dataset or a new version" className="mb-6">
          <ImportPanel
            datasets={items}
            onImported={(result) => {
              datasets.reload();
              setSelected(result.dataset.id);
            }}
          />
        </Card>
      )}
      {datasets.loading && !datasets.data && <Loading />}
      {datasets.error && <ErrorState error={datasets.error} onRetry={datasets.reload} />}
      {datasets.data && items.length === 0 && (
        <EmptyState title="No datasets imported" action={<Button onClick={() => setShowImport(true)}>Import data</Button>}>
          Import a CSV, JSON or JSON Lines file, or load the demo workspace from the dashboard.
        </EmptyState>
      )}
      {items.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-[16rem_1fr]">
          <nav aria-label="Datasets" className="flex flex-col gap-1">
            {items.map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => setSelected(d.id)}
                aria-current={current?.id === d.id ? 'true' : undefined}
                className={cx(
                  'rounded-lg border px-3 py-2 text-left text-sm',
                  current?.id === d.id ? 'border-accent bg-accent/5' : 'border-line bg-surface hover:bg-canvas',
                )}
              >
                <span className="block font-medium text-ink">{d.name}</span>
                <span className="text-xs text-ink-3">
                  {d.version_count} version{d.version_count === 1 ? '' : 's'} · {d.kind}
                </span>
              </button>
            ))}
          </nav>
          {current && <DatasetDetail key={current.id} dataset={current} onChanged={datasets.reload} onDeleted={() => { setSelected(null); datasets.reload(); }} />}
        </div>
      )}
    </>
  );
}

function DatasetDetail({ dataset, onChanged, onDeleted }: { dataset: Dataset; onChanged: () => void; onDeleted: () => void }) {
  const [tab, setTab] = useState<Tab>('versions');
  const versions = useAsync(() => api.versions(dataset.id), [dataset.id, dataset.updated_at]);
  const [versionId, setVersionId] = useState<string>('');
  const effectiveVersion = versionId || dataset.current_version?.id || '';

  return (
    <div className="min-w-0">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{dataset.name}</h2>
          {dataset.description && <p className="text-sm text-ink-2">{dataset.description}</p>}
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="version-select" className="text-sm text-ink-2">
            Version
          </label>
          <select id="version-select" className={inputClass} value={effectiveVersion} onChange={(e) => setVersionId(e.target.value)}>
            {(versions.data ?? []).map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_number} {v.status === 'quarantined' ? '(quarantined)' : ''} {v.id === dataset.current_version?.id ? '— current' : ''}
              </option>
            ))}
          </select>
        </div>
      </div>
      <Tabs
        label="Dataset views"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'versions', label: 'Versions' },
          { id: 'preview', label: 'Preview' },
          { id: 'profile', label: 'Profile' },
          { id: 'quality', label: 'Quality' },
          { id: 'anomalies', label: 'Anomalies' },
        ]}
      />
      {tab === 'versions' && (
        <VersionsView dataset={dataset} versions={versions.data} error={versions.error} reload={() => { versions.reload(); onChanged(); }} onDeleted={onDeleted} />
      )}
      {tab === 'preview' && effectiveVersion && <PreviewView datasetId={dataset.id} versionId={effectiveVersion} />}
      {tab === 'profile' && effectiveVersion && <ProfileView datasetId={dataset.id} versionId={effectiveVersion} />}
      {tab === 'quality' && effectiveVersion && <QualityView datasetId={dataset.id} versionId={effectiveVersion} />}
      {tab === 'anomalies' && effectiveVersion && <AnomaliesView datasetId={dataset.id} versionId={effectiveVersion} />}
    </div>
  );
}

function VersionsView({ dataset, versions, error, reload, onDeleted }: { dataset: Dataset; versions?: Version[]; error?: Error; reload: () => void; onDeleted: () => void }) {
  const [actionError, setActionError] = useState<unknown>();
  const [busy, setBusy] = useState<string>();

  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setActionError(undefined);
    try {
      await fn();
      reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(undefined);
    }
  }

  async function deleteDataset() {
    if (!window.confirm(`Permanently delete "${dataset.name}", all of its versions, rules and results?`)) return;
    setBusy('delete');
    try {
      await api.deleteDataset(dataset.id);
      onDeleted();
    } catch (err) {
      setActionError(err);
      setBusy(undefined);
    }
  }

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!versions) return <Loading />;
  return (
    <Card
      title="Version history"
      actions={
        <Button variant="danger" onClick={deleteDataset} busy={busy === 'delete'}>
          Delete dataset
        </Button>
      }
    >
      {actionError !== undefined && <div className="mb-3"><ErrorState error={actionError} /></div>}
      <div className="overflow-x-auto">
        <table className="tabular w-full text-left text-sm">
          <thead className="text-xs uppercase text-ink-3">
            <tr>
              <th className="pb-2 font-medium">Version</th>
              <th className="pb-2 font-medium">Imported</th>
              <th className="pb-2 font-medium">Source file</th>
              <th className="pb-2 text-right font-medium">Rows</th>
              <th className="pb-2 text-right font-medium">Rejected</th>
              <th className="pb-2 font-medium">SHA-256</th>
              <th className="pb-2 font-medium">Status</th>
              <th className="pb-2" />
            </tr>
          </thead>
          <tbody>
            {[...versions].reverse().map((v) => (
              <tr key={v.id} className="border-t border-line">
                <td className="py-2 font-medium">v{v.version_number}</td>
                <td className="py-2">{formatDate(v.imported_at)}</td>
                <td className="py-2">
                  {v.original_filename} <span className="text-xs text-ink-3">({formatBytes(v.size_bytes)}, {v.origin})</span>
                </td>
                <td className="py-2 text-right">{formatNumber(v.row_count)}</td>
                <td className="py-2 text-right">{v.rejected_row_count}</td>
                <td className="py-2 font-mono text-xs" title={v.sha256}>{v.sha256.slice(0, 12)}…</td>
                <td className="py-2">
                  {v.status === 'quarantined' ? <Badge tone="serious" title={v.status_reason}>Quarantined</Badge> : <Badge tone="good">Active</Badge>}
                </td>
                <td className="py-2 text-right">
                  {v.status === 'active' ? (
                    <Button
                      className="px-2 py-1 text-xs"
                      busy={busy === v.id}
                      onClick={() => act(v.id, () => api.quarantine(dataset.id, v.id, 'Quarantined from the dataset explorer'))}
                    >
                      Quarantine
                    </Button>
                  ) : (
                    <Button className="px-2 py-1 text-xs" busy={busy === v.id} onClick={() => act(v.id, () => api.release(dataset.id, v.id))}>
                      Release
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-ink-3">
        Quarantining keeps the data and makes the newest active version current. Nothing is overwritten; deleting the dataset removes its stored files immediately.
      </p>
    </Card>
  );
}

const PAGE = 25;

function PreviewView({ datasetId, versionId }: { datasetId: string; versionId: string }) {
  const [offset, setOffset] = useState(0);
  const preview = useAsync(() => api.preview(datasetId, { version_id: versionId, offset, limit: PAGE }), [datasetId, versionId, offset]);
  const rejected = useAsync(() => api.rejectedRows(datasetId, versionId), [datasetId, versionId]);
  if (preview.error) return <ErrorState error={preview.error} onRetry={preview.reload} />;
  if (!preview.data) return <Loading />;
  const p = preview.data;
  return (
    <div className="space-y-4">
      <Card title="Parsed rows" actions={<span className="text-xs text-ink-3">Original text values; empty cells are missing</span>}>
        <div className="overflow-x-auto">
          <table className="tabular w-full text-left text-xs">
            <thead>
              <tr>
                <th className="sticky left-0 bg-surface px-2 py-1.5 text-ink-3">#</th>
                {p.columns.map((c) => (
                  <th key={c.name} className="whitespace-nowrap px-2 py-1.5 font-medium">
                    {c.name}
                    <span className="ml-1 font-normal text-ink-3">{c.type}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {p.rows.map((row, i) => (
                <tr key={p.row_numbers[i]} className="border-t border-line">
                  <td className="sticky left-0 bg-surface px-2 py-1 text-ink-3">{p.row_numbers[i]}</td>
                  {row.map((cell, j) => (
                    <td key={j} className="max-w-56 truncate whitespace-nowrap px-2 py-1" title={cell ?? 'missing'}>
                      {cell ?? <span className="italic text-ink-3">null</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination offset={offset} limit={PAGE} total={p.total} onChange={setOffset} />
      </Card>
      {rejected.data && rejected.data.total > 0 && (
        <Card title={`Rejected rows (${rejected.data.total})`}>
          <ul className="space-y-1 font-mono text-xs">
            {rejected.data.rows.slice(0, 50).map((r) => (
              <li key={r.line}>
                line {r.line}: {r.reason} <span className="text-ink-3">{r.preview}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function ProfileView({ datasetId, versionId }: { datasetId: string; versionId: string }) {
  const profile = useAsync(() => api.profile(datasetId, versionId), [datasetId, versionId]);
  if (profile.error) return <ErrorState error={profile.error} onRetry={profile.reload} />;
  if (!profile.data) return <Loading label="Profiling…" />;
  const p = profile.data.profile;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MiniStat label="Rows" value={formatNumber(p.row_count)} />
        <MiniStat label="Columns" value={p.column_count} />
        <MiniStat label="Duplicate rows" value={`${p.duplicate_rows} (${formatPercent(p.duplicate_pct)})`} />
        <MiniStat label="Missing cells" value={formatPercent(p.missing_pct)} />
      </div>
      <p className="text-xs text-ink-3">
        {p.notes.join(' ')} Computed {formatDate(profile.data.computed_at)} in {formatNumber(profile.data.duration_ms)} ms{profile.data.cached ? ' (cached)' : ''}.
      </p>
      <div className="grid gap-4 xl:grid-cols-2">
        {p.columns.map((c) => (
          <ColumnCard key={c.name} column={c} />
        ))}
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-xs text-ink-3">{label}</p>
      <p className="tabular text-lg font-semibold">{value}</p>
    </div>
  );
}

function ColumnCard({ column: c }: { column: ColumnProfile }) {
  const stats: [string, React.ReactNode][] = [
    ['Missing', `${c.null_count} (${formatPercent(c.null_pct)})`],
    ['Distinct', `${formatNumber(c.distinct_count)}${c.unique ? ' — unique' : ''}`],
    ['Invalid', c.invalid_count ? `${c.invalid_count} (e.g. ${c.invalid_examples.slice(0, 2).map((e) => `"${e}"`).join(', ')})` : '0'],
  ];
  if (c.mean !== undefined) {
    stats.push(['Min / max', `${formatNumber(Number(c.min))} / ${formatNumber(Number(c.max))}`]);
    stats.push(['Mean / median', `${formatNumber(c.mean)} / ${formatNumber(c.median)}`]);
    stats.push(['Std dev', formatNumber(c.std ?? NaN)]);
    if (c.quantiles) stats.push(['p05 / p95', `${formatNumber(c.quantiles.p05)} / ${formatNumber(c.quantiles.p95)}`]);
    if (c.outliers) stats.push(['Outliers (MAD / IQR)', `${c.outliers.mad_count ?? 'n/a'} / ${c.outliers.iqr_count ?? 'n/a'}`]);
  }
  if (c.type === 'datetime') {
    stats.push(['Range', `${String(c.min).slice(0, 19)} → ${String(c.max).slice(0, 19)}`]);
    stats.push(['Future-dated', c.future_count ?? 0]);
  }
  if (c.length) stats.push(['Length min/mean/max', `${c.length.min} / ${formatNumber(c.length.mean)} / ${c.length.max}`]);
  if (c.true_count !== undefined) stats.push(['True / false', `${c.true_count} / ${c.false_count}`]);

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <code>{c.name}</code>
          <Badge tone="info">{c.type}</Badge>
          {c.is_categorical && <Badge>categorical</Badge>}
          {c.is_constant && <Badge tone="warning">constant</Badge>}
          {c.mixed && <Badge tone="warning">mixed</Badge>}
        </span>
      }
    >
      <KeyValue items={stats} />
      {c.notes.length > 0 && <p className="mt-2 text-xs text-ink-3">{c.notes.join(' ')}</p>}
      <div className="mt-3">
        {c.histogram && <DistributionChart histogram={c.histogram} label={`Distribution of ${c.name}`} />}
        {!c.histogram && (c.categories ?? c.top_values).length > 0 && c.type !== 'empty' && (
          <FrequencyChart items={c.categories ?? c.top_values} label={`Most frequent values of ${c.name}`} />
        )}
      </div>
    </Card>
  );
}

function QualityView({ datasetId, versionId }: { datasetId: string; versionId: string }) {
  const runs = useAsync(() => api.validations(datasetId, { version_id: versionId, limit: 1 }), [datasetId, versionId]);
  const runId = runs.data?.[0]?.id;
  const run = useAsync(() => api.validation(runId ?? ''), [runId], Boolean(runId));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();

  async function validateNow() {
    setBusy(true);
    setError(undefined);
    try {
      await api.validate(datasetId, { version_id: versionId });
      runs.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Latest validation for this version"
      actions={
        <Button variant="primary" onClick={validateNow} busy={busy}>
          Run enabled rules
        </Button>
      }
    >
      {error !== undefined && <div className="mb-3"><ErrorState error={error} /></div>}
      {runs.error && <ErrorState error={runs.error} onRetry={runs.reload} />}
      {runs.data && runs.data.length === 0 && <EmptyState title="Not validated yet">Define rules on the Quality rules page, then run them here.</EmptyState>}
      {run.data && <ValidationResults run={run.data} />}
      {(runs.loading || run.loading) && <Loading />}
    </Card>
  );
}

export function ValidationResults({ run }: { run: import('../api/types').ValidationRun }) {
  const s = run.summary;
  return (
    <div>
      <p className="mb-3 text-sm text-ink-2">
        {formatDate(run.started_at)} ({run.trigger}) · {s.passed} passed · {s.failed} failed · {s.error} errors · {s.not_evaluated} not evaluated
      </p>
      {s.total === 0 && <p className="text-sm text-ink-2">No enabled rules were run.</p>}
      <ul className="divide-y divide-line">
        {(run.results ?? []).map((r) => (
          <li key={r.id} className="py-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <RuleStatusBadge status={r.status} />
              <SeverityBadge severity={r.severity} />
              <span className="font-medium">{r.rule_name}</span>
              <span className="text-xs text-ink-3">
                {r.rule_type}
                {r.column_name ? ` · ${r.column_name}` : ''}
              </span>
              <span className="tabular ml-auto text-xs text-ink-2">
                {r.violation_count} / {r.evaluated_count} ({formatNumber(r.violation_pct)}%)
              </span>
            </div>
            <p className="mt-1 text-ink-2">{r.message}</p>
            {r.examples.length > 0 && (
              <details className="mt-1 text-xs">
                <summary className="cursor-pointer text-ink-3">Example offending rows</summary>
                <ul className="mt-1 font-mono">
                  {r.examples.map((e) => (
                    <li key={e.row}>
                      row {e.row}: {JSON.stringify(e.values)}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {r.recommendation && <p className="mt-1 text-xs text-ink-2">→ {r.recommendation}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function AnomaliesView({ datasetId, versionId }: { datasetId: string; versionId: string }) {
  const [ml, setMl] = useState(false);
  const result = useAsync(() => api.anomalies(datasetId, { version_id: versionId, include_ml: ml }), [datasetId, versionId, ml]);
  if (result.error) return <ErrorState error={result.error} onRetry={result.reload} />;
  if (!result.data) return <Loading label="Scanning for anomalies…" />;
  const a = result.data;
  return (
    <div className="space-y-4">
      <Card
        title="Robust outliers within this version"
        actions={
          <label className="flex items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" checked={ml} onChange={(e) => setMl(e.target.checked)} /> Include Isolation Forest (optional ML)
          </label>
        }
      >
        {a.outliers.length === 0 ? (
          <p className="text-sm text-ink-2">No values exceed the modified z-score threshold (3.5) in any measure column.</p>
        ) : (
          <ul className="divide-y divide-line text-sm">
            {a.outliers.map((o) => (
              <li key={o.column} className="py-2">
                <span className="font-medium">{o.column}</span>: {o.count} values ({formatNumber(o.pct)}%) by {o.method}. Most extreme:{' '}
                {o.examples.map((e) => `row ${e.row} = ${e.value}`).join(', ')}
              </li>
            ))}
          </ul>
        )}
        {a.outliers_not_applicable.length > 0 && (
          <ul className="mt-2 space-y-1 text-xs text-ink-2">
            {a.outliers_not_applicable.map((s) => (
              <li key={s.column}>
                <span className="font-medium">{s.column}</span>: not applicable — {s.reason}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-ink-3">Outliers inside a single version are often legitimate. Compare versions on the Drift page before acting.</p>
      </Card>
      <Card title="Time-series deviations">
        {!a.time_series ? (
          <p className="text-sm text-ink-2">Needs a timestamp column spanning at least 14 distinct days.</p>
        ) : (
          <>
            <p className="mb-3 text-sm text-ink-2">
              Daily buckets of <code>{a.time_series.column}</code> over {a.time_series.days} days; checked {a.time_series.metrics_checked.join(', ')}.
            </p>
            {a.time_series.skipped && <p className="mb-2 text-sm text-ink-2">{a.time_series.skipped}</p>}
            {!a.time_series.skipped && a.time_series.deviations.length === 0 && <p className="text-sm text-ink-2">No day deviates beyond a robust z-score of 3.5.</p>}
            {Object.entries(a.time_series.series)
              .filter(([metric]) => metric !== 'row_count' || a.time_series?.deviations.some((d) => d.metric === 'row_count'))
              .map(([metric, points]) => {
                const flagged = (a.time_series?.deviations ?? []).filter((d) => d.metric === metric).map((d) => ({ date: d.date, value: d.value }));
                return (
                  <div key={metric} className="mb-4">
                    <p className="mb-1 text-sm font-medium">
                      {metric} <span className="font-normal text-ink-3">— {flagged.length} flagged day(s) marked in red</span>
                    </p>
                    <TimeSeriesChart points={points} flagged={flagged} metric={metric} label={`Daily ${metric}`} />
                  </div>
                );
              })}
          </>
        )}
      </Card>
      {a.ml && (
        <Card title="Isolation Forest (optional)">
          {!a.ml.available || !a.ml.ran ? (
            <p className="text-sm text-ink-2">{a.ml.reason}</p>
          ) : (
            <>
              <p className="mb-2 text-sm text-ink-2">{a.ml.outlier_count} rows scored as anomalous (fixed seed). Highest scores:</p>
              <ul className="font-mono text-xs">
                {a.ml.top_rows?.map((r) => (
                  <li key={r.row}>
                    row {r.row} · score {r.score} · {JSON.stringify(r.values)}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      )}
    </div>
  );
}
