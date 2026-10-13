import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, exportUrl } from '../api/client';
import type { Report } from '../api/types';
import { useDatasets } from '../hooks/useDatasets';
import { Badge, Button, Card, EmptyState, ErrorState, Field, ImpactBadge, Loading, PageHeader, RuleStatusBadge, SeverityBadge } from '../components/ui';
import { formatDate, inputClass } from '../lib/format';
import { useAsync } from '../hooks/useAsync';

export function ReportsPage() {
  const reports = useAsync(() => api.reports(), []);
  const [params, setParams] = useSearchParams();
  const selected = params.get('report') ?? reports.data?.items[0]?.id ?? null;
  const select = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set('report', id);
    else next.delete('report');
    setParams(next, { replace: true });
  };

  return (
    <>
      <PageHeader
        title="Reports"
        description="Investigation reports combine quality results, drift findings, anomaly explanations, downstream impact and recommended actions. Export as Markdown or JSON."
      />
      <div className="grid gap-6 xl:grid-cols-[22rem_1fr]">
        <div className="space-y-6">
          <CreateReport onCreated={(id) => { reports.reload(); select(id); }} />
          <Card title="Saved reports">
            {reports.loading && !reports.data && <Loading />}
            {reports.error && <ErrorState error={reports.error} onRetry={reports.reload} />}
            {reports.data?.items.length === 0 && <p className="text-sm text-ink-2">No reports yet.</p>}
            <ul className="divide-y divide-line">
              {reports.data?.items.map((r) => (
                <li key={r.id}>
                  <button type="button" onClick={() => select(r.id)} aria-current={selected === r.id ? 'true' : undefined} className="w-full py-2 text-left text-sm">
                    <span className={`block font-medium ${selected === r.id ? 'text-accent-strong' : 'text-ink'}`}>{r.title}</span>
                    <span className="text-xs text-ink-3">
                      {r.kind} · {formatDate(r.created_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        </div>
        <div className="min-w-0">
          {selected ? (
            <ReportView key={selected} id={selected} onDeleted={() => { select(null); reports.reload(); }} />
          ) : (
            <EmptyState title="No report selected">Generate a report for a dataset version or a lab experiment.</EmptyState>
          )}
        </div>
      </div>
    </>
  );
}

function CreateReport({ onCreated }: { onCreated: (id: string) => void }) {
  const datasets = useDatasets();
  const [datasetId, setDatasetId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const items = datasets.data?.items ?? [];

  async function submit(event: FormEvent) {
    event.preventDefault();
    const target = datasetId || items[0]?.id;
    if (!target) return;
    setBusy(true);
    setError(undefined);
    try {
      onCreated((await api.createReport({ dataset_id: target })).id);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Generate a report">
      <form onSubmit={submit} className="space-y-3" aria-label="Generate report">
        <Field label="Dataset (current version vs. previous)" htmlFor="report-dataset">
          <select id="report-dataset" className={inputClass} value={datasetId} onChange={(e) => setDatasetId(e.target.value)} disabled={items.length === 0}>
            {items.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </Field>
        <Button type="submit" variant="primary" busy={busy} disabled={items.length === 0}>
          Generate report
        </Button>
        <p className="text-xs text-ink-3">Experiment reports are generated from the Fault lab.</p>
        {error !== undefined && <ErrorState error={error} />}
      </form>
    </Card>
  );
}

function ReportView({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const report = useAsync(() => api.report(id), [id]);
  const [error, setError] = useState<unknown>();
  if (report.error) return <ErrorState error={report.error} onRetry={report.reload} />;
  if (!report.data) return <Loading />;
  const r = report.data;
  const c = r.content;

  async function remove() {
    if (!window.confirm('Delete this report?')) return;
    try {
      await api.deleteReport(r.id);
      onDeleted();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <Card
      title={r.title}
      actions={
        <>
          <a className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium hover:bg-canvas" href={exportUrl(r.id, 'markdown')} download>
            Export Markdown
          </a>
          <a className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium hover:bg-canvas" href={exportUrl(r.id, 'json')} download>
            Export JSON
          </a>
          <Button variant="danger" onClick={remove}>
            Delete
          </Button>
        </>
      }
    >
      {error !== undefined && <ErrorState error={error} />}
      <p className="text-xs text-ink-3">Generated {formatDate(c.generated_at)} · {String(c.generator ?? '')}</p>
      {r.kind === 'experiment' ? <ExperimentSections content={c} /> : <DatasetSections content={c} />}
      <Section title="Downstream impact">
        {!c.impact ? (
          <p className="text-sm text-ink-2">Not connected to the lineage graph.</p>
        ) : (
          <>
            <p className="text-sm">{c.impact.assessment}</p>
            <ul className="mt-2 space-y-1 text-sm">
              {c.impact.impacted.map((i) => (
                <li key={i.name} className="flex flex-wrap items-center gap-2">
                  <ImpactBadge value={i.classification} /> {i.name} <span className="text-xs text-ink-3">{i.path.join(' → ')}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>
      {(c.recommendations?.length ?? 0) > 0 && (
        <Section title="Recommended actions">
          <ol className="list-decimal space-y-2 pl-5 text-sm">
            {c.recommendations?.map((rec) => (
              <li key={rec.priority}>
                <Badge tone={rec.kind === 'contain' ? 'critical' : 'info'}>{rec.kind}</Badge> <strong>{rec.title}</strong>
                <p className="text-ink-2">{rec.rationale}</p>
              </li>
            ))}
          </ol>
        </Section>
      )}
      <p className="mt-6 border-t border-line pt-3 text-xs italic text-ink-3">{String(c.disclaimer ?? '')}</p>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-3">{title}</h3>
      {children}
    </section>
  );
}

function DriftSection({ drift }: { drift: Report['content']['drift'] }) {
  return (
    <Section title="Drift findings">
      {!drift || drift.status !== 'compared' ? (
        <p className="text-sm text-ink-2">{drift?.message ?? 'No comparison available.'}</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {drift.schema_changes?.map((s, i) => (
            <li key={`s${i}`}>
              <SeverityBadge severity={s.severity} /> {s.change_type.replace(/_/g, ' ')} <code className="text-xs">{s.column}</code>
            </li>
          ))}
          {drift.signals?.map((s, i) => (
            <li key={`${s.key}-${s.source}-${i}`}>
              <SeverityBadge severity={s.severity} /> {s.title}
            </li>
          ))}
          {!drift.signals?.length && !drift.schema_changes?.length && <li className="text-ink-2">No actionable drift.</li>}
        </ul>
      )}
    </Section>
  );
}

function DatasetSections({ content: c }: { content: Report['content'] }) {
  const q = c.quality;
  return (
    <>
      <Section title="Quality summary">
        {!q || q.status === 'no_rules' ? (
          <p className="text-sm text-ink-2">{q?.message ?? 'No rules.'}</p>
        ) : (
          <>
            <p className="text-sm">
              {q.summary?.passed} passed · {q.summary?.failed} failed · {q.summary?.error} errors · {q.summary?.not_evaluated} not evaluated
            </p>
            <ul className="mt-2 space-y-1 text-sm">
              {q.results?.map((res) => (
                <li key={res.rule_name} className="flex flex-wrap items-center gap-2">
                  <RuleStatusBadge status={res.status} /> {res.rule_name}
                  <span className="text-xs text-ink-3">{res.violation_count} violations — {res.message}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>
      <DriftSection drift={c.drift} />
      <Section title="Anomaly explanations">
        <ul className="space-y-1 text-sm">
          {((c.anomalies as { signals?: { key: string; title: string; explanation: string; severity: 'low' }[] })?.signals ?? []).map((s, i) => (
            <li key={`${s.key}-${i}`}>
              <SeverityBadge severity={s.severity} /> <strong>{s.title}</strong> — <span className="text-ink-2">{s.explanation}</span>
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}

function ExperimentSections({ content: c }: { content: Report['content'] }) {
  const ev = c.evaluation;
  return (
    <>
      <Section title="Evaluation against ground truth">
        <p className="text-sm">
          Outcome <strong>{ev?.outcome}</strong> · {ev?.true_positives.length} true-positive signals · {ev?.false_positives.length} false positives · {ev?.missed_signals.length} missed
        </p>
      </Section>
      <DriftSection drift={c.drift} />
    </>
  );
}
