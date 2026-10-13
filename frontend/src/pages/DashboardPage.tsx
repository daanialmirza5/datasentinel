import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useAsync } from '../hooks/useAsync';
import { Button, Card, EmptyState, ErrorState, HealthBadge, ImpactBadge, Loading, PageHeader, SeverityBadge, StatCard } from '../components/ui';
import { formatDate, formatNumber } from '../lib/format';

export function DashboardPage() {
  const { data, error, loading, reload } = useAsync(() => api.dashboard(), []);
  const [seeding, setSeeding] = useState(false);
  const [seedError, setSeedError] = useState<unknown>();

  async function loadSamples() {
    setSeeding(true);
    setSeedError(undefined);
    try {
      await api.loadSamples();
      reload();
    } catch (err) {
      setSeedError(err);
    } finally {
      setSeeding(false);
    }
  }

  if (loading && !data) return <Loading label="Loading dashboard…" />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  if (data.dataset_count === 0) {
    return (
      <>
        <PageHeader title="Dashboard" description="Catch silent data failures before they corrupt your decisions." />
        <EmptyState
          title="No datasets yet"
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="primary" onClick={loadSamples} busy={seeding}>
                Load demo workspace
              </Button>
              <Link to="/datasets" className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium hover:bg-canvas">
                Import your own data
              </Link>
            </div>
          }
        >
          The demo workspace imports five synthetic datasets (including three monthly order exports with planted issues), quality rules and a
          lineage graph. Everything stays on this machine.
        </EmptyState>
        {seedError !== undefined && <div className="mt-4"><ErrorState error={seedError} /></div>}
      </>
    );
  }

  const rules = data.rule_status;
  const impactCounts = data.impact.counts;
  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Current health of every dataset version, computed from stored validation runs and version comparisons."
        actions={<Button onClick={reload} busy={loading}>Refresh</Button>}
      />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Datasets" value={data.dataset_count} hint={`${data.version_count} versions tracked`} />
        <StatCard
          label="Rule results"
          value={`${rules.failed} failed`}
          tone={rules.failed ? 'bad' : 'good'}
          hint={`${rules.passed} passed · ${rules.error} errors · ${rules.not_evaluated} not evaluated`}
        />
        <StatCard label="Active anomalies" value={data.active_anomalies.count} tone={data.active_anomalies.count ? 'bad' : 'good'} hint="Signals on current versions vs. their predecessor" />
        <StatCard
          label="Impacted downstream"
          value={data.impact.impacted.length}
          tone={data.impact.impacted.length ? 'bad' : 'good'}
          hint={`${impactCounts.confirmed_failure} confirmed · ${impactCounts.suspected_impact} suspected · ${impactCounts.unverified_risk} unverified`}
        />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card title="Dataset health" className="xl:col-span-2">
          <div className="overflow-x-auto">
            <table className="tabular w-full text-left text-sm">
              <thead className="text-xs uppercase text-ink-3">
                <tr>
                  <th className="pb-2 font-medium">Dataset</th>
                  <th className="pb-2 font-medium">Version</th>
                  <th className="pb-2 pr-6 text-right font-medium">Rows</th>
                  <th className="pb-2 font-medium">Rules</th>
                  <th className="pb-2 text-right font-medium">Signals</th>
                </tr>
              </thead>
              <tbody>
                {data.datasets.map((d) => (
                  <tr key={d.dataset_id} className="border-t border-line">
                    <td className="py-2">
                      <Link className="font-medium text-accent-strong hover:underline" to={`/datasets?dataset=${d.dataset_id}`}>
                        {d.name}
                      </Link>
                    </td>
                    <td className="py-2">v{d.version_number}</td>
                    <td className="py-2 pr-6 text-right">{formatNumber(d.row_count)}</td>
                    <td className="py-2">
                      <HealthBadge state={d.health} /> {d.failed_rules > 0 && <span className="text-xs text-ink-2">{d.failed_rules} failed</span>}
                    </td>
                    <td className="py-2 text-right">{d.signals}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Recent imports">
          <ul className="space-y-3 text-sm">
            {data.recent_imports.map((imp) => (
              <li key={imp.version_id} className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <Link to={`/datasets?dataset=${imp.dataset_id}`} className="font-medium text-ink hover:underline">
                    {imp.dataset_name} v{imp.version_number}
                  </Link>
                  <p className="text-xs text-ink-3">{formatDate(imp.imported_at)} · {imp.origin}</p>
                </div>
                <span className="tabular shrink-0 text-xs text-ink-2">{formatNumber(imp.row_count)} rows</span>
              </li>
            ))}
          </ul>
        </Card>

        <Card title={`Active anomalies (${data.active_anomalies.count})`} className="xl:col-span-2" actions={<Link to="/drift" className="text-sm text-accent-strong hover:underline">Open drift monitoring</Link>}>
          {data.active_anomalies.items.length === 0 ? (
            <p className="text-sm text-ink-2">No actionable signals on current versions.</p>
          ) : (
            <ul className="divide-y divide-line">
              {data.active_anomalies.items.map((s) => (
                <li key={`${s.dataset_id}-${s.key}`} className="flex items-start gap-3 py-2.5 text-sm">
                  <SeverityBadge severity={s.severity} />
                  <div className="min-w-0">
                    <p className="font-medium text-ink">{s.title}</p>
                    <p className="text-xs text-ink-3">
                      {s.dataset_name} v{s.version_number} · {s.label} · {s.source}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title={`Recent schema changes (${data.schema_changes.count})`}>
          {data.schema_changes.items.length === 0 ? (
            <p className="text-sm text-ink-2">No schema changes between current and previous versions.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {data.schema_changes.items.map((c, i) => (
                <li key={i} className="flex items-start gap-2">
                  <SeverityBadge severity={c.severity} />
                  <span>
                    <span className="font-medium">{c.change_type.replace(/_/g, ' ')}</span> <code className="text-xs">{c.column}</code>
                    <span className="block text-xs text-ink-3">{c.dataset_name} v{c.version_number}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Impacted downstream assets" className="xl:col-span-3" actions={<Link to="/lineage" className="text-sm text-accent-strong hover:underline">Open lineage</Link>}>
          {data.impact.impacted.length === 0 ? (
            <p className="text-sm text-ink-2">No failing or anomalous datasets currently feed other assets.</p>
          ) : (
            <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {data.impact.impacted.map((i) => (
                <li key={i.id} className="flex items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm">
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{i.name}</span>
                    <span className="text-xs text-ink-3">{i.kind} · via {i.via}</span>
                  </span>
                  <ImpactBadge value={i.classification} />
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-ink-3">
            Impact follows declared lineage only. “Suspected” and “unverified” mean the asset depends on a failing input — not that its output is known to be wrong.
          </p>
        </Card>
      </div>
    </>
  );
}
