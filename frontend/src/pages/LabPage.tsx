import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { Dataset, Experiment, FaultType } from '../api/types';
import { ComparisonChart } from '../components/charts';
import { DatasetPicker } from '../components/DatasetPicker';
import { useDatasets, useSelectedDataset } from '../hooks/useDatasets';
import { Badge, Button, Card, EmptyState, ErrorState, Field, ImpactBadge, Loading, PageHeader, SeverityBadge, StatCard } from '../components/ui';
import { formatDate, formatNumber, inputClass } from '../lib/format';
import { useAsync } from '../hooks/useAsync';
import { buildParams, propType } from '../lib/schemaParams';

export function LabPage() {
  const datasets = useDatasets();
  const [selected, setSelected] = useSelectedDataset();
  const items = (datasets.data?.items ?? []).filter((d) => d.kind !== 'lab');
  const dataset = items.find((d) => d.id === selected);
  return (
    <>
      <PageHeader
        title="Fault injection laboratory"
        description="Inject a controlled, seeded fault into a copy of a dataset version, run the same detection pipeline, and score what it found against the hidden ground truth. Originals are never modified."
        actions={items.length > 0 && <DatasetPicker datasets={items} value={selected} onChange={setSelected} />}
      />
      {datasets.loading && !datasets.data && <Loading />}
      {datasets.error && <ErrorState error={datasets.error} onRetry={datasets.reload} />}
      {datasets.data && items.length === 0 && <EmptyState title="No datasets">Import a dataset or load the demo workspace first.</EmptyState>}
      {dataset && <LabWorkspace key={dataset.id} dataset={dataset} />}
    </>
  );
}

function LabWorkspace({ dataset }: { dataset: Dataset }) {
  const catalogue = useAsync(() => api.faultTypes(dataset.id), [dataset.id]);
  const history = useAsync(() => api.experiments({ dataset_id: dataset.id, limit: 20 }), [dataset.id]);
  const [experiment, setExperiment] = useState<Experiment>();
  const [loadingId, setLoadingId] = useState<string>();

  async function open(id: string) {
    setLoadingId(id);
    try {
      setExperiment(await api.experiment(id));
    } finally {
      setLoadingId(undefined);
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[24rem_1fr]">
      <div className="space-y-6">
        {catalogue.error && <ErrorState error={catalogue.error} onRetry={catalogue.reload} />}
        {catalogue.data ? (
          <ScenarioForm
            dataset={dataset}
            faults={catalogue.data.fault_types}
            onRan={(exp) => {
              setExperiment(exp);
              history.reload();
            }}
          />
        ) : (
          !catalogue.error && <Loading />
        )}
        <Card title="Experiment history">
          {history.data?.items.length === 0 && <p className="text-sm text-ink-2">No experiments on this dataset yet.</p>}
          <ul className="divide-y divide-line">
            {history.data?.items.map((e) => (
              <li key={e.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                <button type="button" className="min-w-0 text-left" onClick={() => open(e.id)}>
                  <span className="block truncate font-medium text-accent-strong hover:underline">{e.fault_type.replace(/_/g, ' ')}</span>
                  <span className="text-xs text-ink-3">
                    seed {e.seed} · {formatDate(e.created_at)}
                  </span>
                </button>
                {loadingId === e.id ? <Loading label="" /> : <OutcomeBadge outcome={e.outcome} />}
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <div className="min-w-0">
        {experiment ? (
          <ExperimentView
            key={experiment.id + experiment.created_at}
            experiment={experiment}
            onChanged={(exp) => {
              setExperiment(exp ?? undefined);
              history.reload();
            }}
          />
        ) : (
          <EmptyState title="Run a scenario">Choose a fault, adjust its parameters and seed, then run it. Results appear here.</EmptyState>
        )}
      </div>
    </div>
  );
}

export function OutcomeBadge({ outcome }: { outcome: Experiment['outcome'] }) {
  if (outcome === 'detected') return <Badge tone="good">Detected</Badge>;
  if (outcome === 'partially_detected') return <Badge tone="warning">Partially detected</Badge>;
  if (outcome === 'missed') return <Badge tone="critical">Missed</Badge>;
  return <Badge>Unknown</Badge>;
}

function ScenarioForm({ dataset, faults, onRan }: { dataset: Dataset; faults: FaultType[]; onRan: (exp: Experiment) => void }) {
  const [faultType, setFaultType] = useState(faults[0]?.fault_type ?? '');
  const [values, setValues] = useState<Record<string, string>>({});
  const [seed, setSeed] = useState('42');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const fault = faults.find((f) => f.fault_type === faultType);
  const eligible = fault?.eligible_columns;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!fault) return;
    setBusy(true);
    setError(undefined);
    try {
      const params = buildParams(fault.params_schema, values);
      onRan(await api.createExperiment({ dataset_id: dataset.id, fault_type: fault.fault_type, params, seed: Number(seed) }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Scenario">
      <form onSubmit={submit} className="space-y-4" aria-label="Fault scenario">
        <Field label="Fault" htmlFor="fault-type" hint={fault?.description}>
          <select id="fault-type" className={inputClass} value={faultType} onChange={(e) => { setFaultType(e.target.value); setValues({}); }}>
            {faults.map((f) => (
              <option key={f.fault_type} value={f.fault_type}>
                {f.label}
              </option>
            ))}
          </select>
        </Field>
        {fault?.note && <p className="rounded-md bg-warning/10 px-3 py-2 text-xs text-warning-ink">! {fault.note}</p>}
        {Object.entries(fault?.params_schema.properties ?? {}).map(([key, prop]) => {
          const id = `fault-${key}`;
          const label = key.replace(/_/g, ' ');
          if (key === 'column') {
            return (
              <Field key={key} label="Target column" htmlFor={id} hint={eligible && eligible.length === 0 ? 'No suitable column in this dataset.' : 'Leave on automatic to let the seed choose.'}>
                <select id={id} className={inputClass} value={values.column ?? ''} onChange={(e) => setValues({ ...values, column: e.target.value })}>
                  <option value="">Automatic (seeded)</option>
                  {(eligible ?? dataset.current_version?.schema.map((c) => c.name) ?? []).map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </Field>
            );
          }
          const { type } = propType(prop);
          if (prop.enum) {
            return (
              <Field key={key} label={label} htmlFor={id}>
                <select id={id} className={inputClass} value={values[key] ?? String(prop.default ?? '')} onChange={(e) => setValues({ ...values, [key]: e.target.value })}>
                  {prop.enum.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              </Field>
            );
          }
          return (
            <Field key={key} label={label} htmlFor={id} hint={prop.description ?? (type === 'array' ? 'Comma-separated' : undefined)}>
              <input
                id={id}
                className={inputClass}
                type={type === 'number' || type === 'integer' ? 'number' : 'text'}
                step="any"
                value={values[key] ?? ''}
                placeholder={prop.default !== undefined ? (Array.isArray(prop.default) ? prop.default.join(', ') : String(prop.default)) : ''}
                onChange={(e) => setValues({ ...values, [key]: e.target.value })}
              />
            </Field>
          );
        })}
        <Field label="Random seed" htmlFor="fault-seed" hint="The same seed reproduces byte-identical data.">
          <input id="fault-seed" type="number" min={0} className={inputClass} value={seed} onChange={(e) => setSeed(e.target.value)} />
        </Field>
        {error !== undefined && <ErrorState error={error} />}
        <Button type="submit" variant="primary" busy={busy} className="w-full">
          Inject fault and run detection
        </Button>
        <p className="text-xs text-ink-3">Expected signals: {fault?.expected_signals.join(', ')}. The detector never sees this or the ground truth.</p>
      </form>
    </Card>
  );
}

function ExperimentView({ experiment: e, onChanged }: { experiment: Experiment; onChanged: (exp: Experiment | null) => void }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<unknown>();
  const [note, setNote] = useState<string>();
  const ev = e.evaluation;
  const gt = e.ground_truth;
  if (!ev || !gt || !e.detection) return <Loading />;

  async function act(key: string, fn: () => Promise<void>) {
    setBusy(key);
    setError(undefined);
    setNote(undefined);
    try {
      await fn();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(undefined);
    }
  }

  const tpKeys = new Set(ev.true_positives.map((s) => s.key + s.source));
  const affected = gt.affected_columns;
  const charts = e.detection.column_comparisons.filter((c) => affected.includes(c.column) && c.chart);

  return (
    <div className="space-y-6">
      <Card
        title={
          <span className="flex flex-wrap items-center gap-2">
            {e.fault_type.replace(/_/g, ' ')} on {e.dataset_name} v{e.base_version_number}
            <OutcomeBadge outcome={e.outcome} />
          </span>
        }
        actions={
          <>
            <Button
              busy={busy === 'same'}
              onClick={() =>
                act('same', async () => {
                  const next = await api.regenerateExperiment(e.id);
                  setNote(next.evaluation?.modified_sha256 === ev.modified_sha256 ? 'Regenerated with the same seed: data is byte-identical (SHA-256 matches).' : 'Regenerated: data differs.');
                  onChanged(next);
                })
              }
            >
              Regenerate
            </Button>
            <Button busy={busy === 'new'} onClick={() => act('new', async () => onChanged(await api.regenerateExperiment(e.id, Math.floor(Math.random() * 1_000_000))))}>
              New seed
            </Button>
            <Button busy={busy === 'report'} onClick={() => act('report', async () => { const r = await api.createReport({ experiment_id: e.id }); navigate(`/reports?report=${r.id}`); })}>
              Report
            </Button>
            <Button variant="danger" busy={busy === 'reset'} onClick={() => act('reset', async () => { await api.deleteExperiment(e.id); onChanged(null); })}>
              Reset
            </Button>
          </>
        }
      >
        {error !== undefined && <div className="mb-3"><ErrorState error={error} /></div>}
        {note && <p role="status" className="mb-3 text-sm text-good-ink">✓ {note}</p>}
        <p className="text-sm text-ink-2">
          Seed {e.seed} · parameters <code className="text-xs">{JSON.stringify(e.params)}</code> · rows {formatNumber(ev.base_rows)} → {formatNumber(ev.modified_rows)} · ran in {formatNumber(e.duration_ms)} ms
        </p>
        <p className="mt-1 font-mono text-xs text-ink-3">modified data SHA-256 {ev.modified_sha256}</p>
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="Expected signals" value={ev.expected_signals.length} />
          <StatCard label="Matched" value={ev.matched_signals.length} tone={ev.matched_signals.length ? 'good' : 'bad'} />
          <StatCard label="Missed" value={ev.missed_signals.length} tone={ev.missed_signals.length ? 'bad' : 'good'} />
          <StatCard label="False positives" value={ev.false_positives.length} tone={ev.false_positives.length ? 'bad' : 'good'} hint={ev.signal_precision !== null ? `signal precision ${formatNumber(ev.signal_precision * 100)}%` : undefined} />
        </div>
      </Card>

      <div className="grid gap-6 2xl:grid-cols-2">
        <Card title="Ground truth (hidden from the detector)">
          <p className="text-sm">
            Scope <strong>{gt.scope}</strong>; affected {affected.length ? <code>{affected.join(', ')}</code> : 'rows (dataset-level)'}; {gt.affected_rows} rows modified. Expected:{' '}
            {gt.expected.primary.join(', ')}.
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-ink-3">
                <tr>
                  <th className="pb-1 font-medium">Row</th>
                  <th className="pb-1 font-medium">Before</th>
                  <th className="pb-1 font-medium">After</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {gt.examples.map((ex, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="py-1">{ex.row ?? '—'}</td>
                    <td className="py-1">{ex.before ? JSON.stringify(ex.before) : ex.note ?? ''}</td>
                    <td className="py-1">{ex.after ? JSON.stringify(ex.after) : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Detection vs. ground truth">
          {ev.missed_signals.length > 0 && (
            <div className="mb-3">
              <p className="text-xs font-semibold uppercase text-critical">Missed</p>
              <ul className="text-sm">
                {ev.missed_signals.map((m) => (
                  <li key={m.category + m.column}>✕ {m.category} {m.column && <code className="text-xs">{m.column}</code>}</li>
                ))}
              </ul>
            </div>
          )}
          <ul className="divide-y divide-line">
            {e.detection.signals.map((s, index) => {
              const tp = tpKeys.has(s.key + s.source);
              const scored = s.severity !== 'info';
              return (
                <li key={`${s.key}-${s.source}-${index}`} className="py-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    {scored ? tp ? <Badge tone="good">True positive</Badge> : <Badge tone="critical">False positive</Badge> : <Badge>Context (not scored)</Badge>}
                    <SeverityBadge severity={s.severity} />
                    <span className="font-medium">{s.title}</span>
                    <Badge>{s.source}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-ink-2">{s.explanation}</p>
                </li>
              );
            })}
            {e.detection.signals.length === 0 && <li className="py-2 text-sm text-ink-3">No signals were raised.</li>}
          </ul>
        </Card>
      </div>

      {charts.length > 0 && (
        <Card title="Before vs. after">
          <div className="grid gap-6 xl:grid-cols-2">
            {charts.map((c) => (
              <div key={c.column}>
                <p className="mb-1 text-sm font-medium">
                  <code>{c.column}</code>
                </p>
                {c.chart && <ComparisonChart chart={c.chart} label={`${c.column}: original vs. modified`} baseLabel="Original" candidateLabel="Modified" />}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title={`Simulated downstream impact (origin: ${ev.simulated_impact.simulated_origin_state})`}>
        {ev.simulated_impact.impacted.length === 0 ? (
          <p className="text-sm text-ink-2">This dataset has no declared downstream dependencies.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {ev.simulated_impact.impacted.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center gap-2">
                <ImpactBadge value={i.classification} /> <span className="font-medium">{i.name}</span>
                <span className="text-xs text-ink-3">{i.path.join(' → ')}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-ink-3">What would be affected if this modified data reached production, based on declared lineage.</p>
      </Card>
    </div>
  );
}
