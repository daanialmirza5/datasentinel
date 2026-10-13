import { useState, type FormEvent } from 'react';
import { api } from '../api/client';
import type { Dataset, Rule, RuleInput, RuleTypeInfo, Severity, ValidationRun } from '../api/types';
import { DatasetPicker } from '../components/DatasetPicker';
import { useDatasets, useSelectedDataset } from '../hooks/useDatasets';
import { Badge, Button, Card, EmptyState, ErrorState, Field, Loading, PageHeader, SeverityBadge } from '../components/ui';
import { inputClass } from '../lib/format';
import { useAsync } from '../hooks/useAsync';
import { ValidationResults } from './DatasetsPage';
import { buildParams, paramsToStrings, propType, type SchemaProp } from '../lib/schemaParams';

export function RulesPage() {
  const datasets = useDatasets();
  const [selected, setSelected] = useSelectedDataset();
  const ruleTypes = useAsync(() => api.ruleTypes(), []);
  const items = datasets.data?.items ?? [];
  const dataset = items.find((d) => d.id === selected);

  return (
    <>
      <PageHeader
        title="Quality rules"
        description="Declare expectations as rules. Each run reports passed, failed, error or not evaluated — a rule that could not run is never shown as passing."
        actions={items.length > 0 && <DatasetPicker datasets={items} value={selected} onChange={setSelected} />}
      />
      {(datasets.loading || ruleTypes.loading) && !dataset && <Loading />}
      {datasets.error && <ErrorState error={datasets.error} onRetry={datasets.reload} />}
      {ruleTypes.error && <ErrorState error={ruleTypes.error} onRetry={ruleTypes.reload} />}
      {datasets.data && items.length === 0 && <EmptyState title="No datasets">Import a dataset before defining rules.</EmptyState>}
      {dataset && ruleTypes.data && <RulesWorkspace key={dataset.id} dataset={dataset} datasets={items} ruleTypes={ruleTypes.data.types} />}
    </>
  );
}

function RulesWorkspace({ dataset, datasets, ruleTypes }: { dataset: Dataset; datasets: Dataset[]; ruleTypes: RuleTypeInfo[] }) {
  const rules = useAsync(() => api.rules(dataset.id), [dataset.id]);
  const suggestions = useAsync(() => api.suggestions(dataset.id), [dataset.id, rules.data?.length]);
  const [editing, setEditing] = useState<Rule | 'new' | null>(null);
  const [run, setRun] = useState<ValidationRun>();
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<unknown>();
  const columns = dataset.current_version?.schema.map((c) => c.name) ?? [];

  async function act(key: string, fn: () => Promise<unknown>, reloadRules = true) {
    setBusy(key);
    setError(undefined);
    try {
      await fn();
      if (reloadRules) rules.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(undefined);
    }
  }

  const runRules = (ruleIds?: string[]) =>
    act(ruleIds ? `run-${ruleIds[0]}` : 'run', async () => setRun(await api.validate(dataset.id, ruleIds ? { rule_ids: ruleIds } : {})), false);

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_24rem]">
      <div className="space-y-6">
        <Card
          title={`Rules for ${dataset.name}`}
          actions={
            <>
              <Button onClick={() => setEditing('new')}>New rule</Button>
              <Button variant="primary" onClick={() => runRules()} busy={busy === 'run'} disabled={!rules.data?.some((r) => r.enabled)}>
                Run enabled rules
              </Button>
            </>
          }
        >
          {error !== undefined && <div className="mb-3"><ErrorState error={error} /></div>}
          {rules.error && <ErrorState error={rules.error} onRetry={rules.reload} />}
          {rules.data && rules.data.length === 0 && <EmptyState title="No rules yet">Create one, or accept a suggestion derived from the current profile.</EmptyState>}
          {rules.data && rules.data.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs uppercase text-ink-3">
                  <tr>
                    <th className="pb-2 font-medium">Enabled</th>
                    <th className="pb-2 font-medium">Rule</th>
                    <th className="pb-2 font-medium">Type</th>
                    <th className="pb-2 font-medium">Severity</th>
                    <th className="pb-2" />
                  </tr>
                </thead>
                <tbody>
                  {rules.data.map((rule) => (
                    <tr key={rule.id} className="border-t border-line">
                      <td className="py-2">
                        <input
                          type="checkbox"
                          aria-label={`${rule.enabled ? 'Disable' : 'Enable'} ${rule.name}`}
                          checked={rule.enabled}
                          disabled={busy === `toggle-${rule.id}`}
                          onChange={() => act(`toggle-${rule.id}`, () => api.updateRule(rule.id, { enabled: !rule.enabled }))}
                        />
                      </td>
                      <td className="py-2">
                        <span className="font-medium">{rule.name}</span>
                        <span className="block text-xs text-ink-3">
                          {rule.column_name ?? 'whole dataset'} · {JSON.stringify(rule.params)}
                        </span>
                      </td>
                      <td className="py-2 text-xs">{rule.rule_type}</td>
                      <td className="py-2">
                        <SeverityBadge severity={rule.severity} />
                      </td>
                      <td className="whitespace-nowrap py-2 text-right">
                        <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => runRules([rule.id])} busy={busy === `run-${rule.id}`}>
                          Run
                        </Button>
                        <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setEditing(rule)}>
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          className="px-2 py-1 text-xs text-critical"
                          busy={busy === `del-${rule.id}`}
                          onClick={() => window.confirm(`Delete rule "${rule.name}"?`) && act(`del-${rule.id}`, () => api.deleteRule(rule.id))}
                        >
                          Delete
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        {editing && (
          <RuleForm
            key={editing === 'new' ? 'new' : editing.id}
            dataset={dataset}
            datasets={datasets}
            columns={columns}
            ruleTypes={ruleTypes}
            rule={editing === 'new' ? undefined : editing}
            onCancel={() => setEditing(null)}
            onSaved={() => {
              setEditing(null);
              rules.reload();
            }}
          />
        )}
        {run && (
          <Card title="Validation results" actions={<Button variant="ghost" onClick={() => setRun(undefined)}>Close</Button>}>
            <ValidationResults run={run} />
          </Card>
        )}
      </div>
      <Card title="Suggested rules">
        {suggestions.loading && <Loading />}
        {suggestions.error && <ErrorState error={suggestions.error} onRetry={suggestions.reload} />}
        {suggestions.data?.suggestions.length === 0 && <p className="text-sm text-ink-2">No further suggestions for this profile.</p>}
        <ul className="space-y-3">
          {suggestions.data?.suggestions.slice(0, 12).map((s) => (
            <li key={`${s.rule_type}-${s.column_name}`} className="rounded-lg border border-line p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{s.name}</span>
                <Button
                  className="px-2 py-1 text-xs"
                  busy={busy === `sug-${s.name}`}
                  onClick={() =>
                    act(`sug-${s.name}`, () =>
                      api.createRule(dataset.id, { name: s.name, rule_type: s.rule_type, column_name: s.column_name, params: s.params, severity: s.severity }),
                    )
                  }
                >
                  Add
                </Button>
              </div>
              <p className="mt-1 text-xs text-ink-3">{s.reason}</p>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-ink-3">Suggestions are derived from the observed profile; nothing is created until you add it.</p>
      </Card>
    </div>
  );
}

function RuleForm({ dataset, datasets, columns, ruleTypes, rule, onCancel, onSaved }: {
  dataset: Dataset;
  datasets: Dataset[];
  columns: string[];
  ruleTypes: RuleTypeInfo[];
  rule?: Rule;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [ruleType, setRuleType] = useState(rule?.rule_type ?? 'not_null');
  const [name, setName] = useState(rule?.name ?? '');
  const [column, setColumn] = useState(rule?.column_name ?? columns[0] ?? '');
  const [severity, setSeverity] = useState<Severity>(rule?.severity ?? 'medium');
  const [values, setValues] = useState<Record<string, string>>(rule ? paramsToStrings(rule.params) : {});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const info = ruleTypes.find((t) => t.rule_type === ruleType);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!info) return;
    setBusy(true);
    setError(undefined);
    const body: RuleInput = {
      name: name.trim() || `${info.label}${column && info.requires_column ? ` · ${column}` : ''}`,
      rule_type: ruleType,
      column_name: info.requires_column ? column : null,
      params: buildParams(info.params_schema, values),
      severity,
    };
    try {
      if (rule) await api.updateRule(rule.id, { name: body.name, column_name: body.column_name, params: body.params, severity: body.severity });
      else await api.createRule(dataset.id, body);
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={rule ? `Edit rule: ${rule.name}` : 'New rule'}>
      <form onSubmit={submit} className="space-y-4" aria-label={rule ? 'Edit rule' : 'Create rule'}>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Rule type" htmlFor="rule-type" hint={info?.description}>
            <select id="rule-type" className={inputClass} value={ruleType} disabled={Boolean(rule)} onChange={(e) => { setRuleType(e.target.value); setValues({}); }}>
              {ruleTypes.map((t) => (
                <option key={t.rule_type} value={t.rule_type}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Name" htmlFor="rule-name">
            <input id="rule-name" className={inputClass} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="Defaults to the rule type" />
          </Field>
          {info?.requires_column && (
            <Field label="Column" htmlFor="rule-column">
              <select id="rule-column" className={inputClass} value={column} onChange={(e) => setColumn(e.target.value)}>
                {!columns.includes(column) && column && <option value={column}>{column} (not in current version)</option>}
                {columns.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Severity" htmlFor="rule-severity">
            <select id="rule-severity" className={inputClass} value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
              {['low', 'medium', 'high', 'critical'].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
          {Object.entries(info?.params_schema.properties ?? {}).map(([key, raw]) => {
            const prop = raw as SchemaProp;
            const { type, format } = propType(prop);
            const id = `param-${key}`;
            const label = key.replace(/_/g, ' ');
            if (key === 'reference_dataset_id') {
              return (
                <Field key={key} label="Reference dataset" htmlFor={id}>
                  <select id={id} className={inputClass} value={values[key] ?? ''} onChange={(e) => setValues({ ...values, [key]: e.target.value })}>
                    <option value="">Choose…</option>
                    {datasets.filter((d) => d.id !== dataset.id).map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </Field>
              );
            }
            if (type === 'enum' && prop.enum) {
              return (
                <Field key={key} label={label} htmlFor={id}>
                  <select id={id} className={inputClass} value={values[key] ?? ''} onChange={(e) => setValues({ ...values, [key]: e.target.value })}>
                    <option value="">Choose…</option>
                    {prop.enum.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </Field>
              );
            }
            if (type === 'boolean') {
              const checked = (values[key] ?? String(prop.default ?? false)) === 'true';
              return (
                <label key={key} className="flex items-center gap-2 self-end text-sm text-ink-2">
                  <input type="checkbox" checked={checked} onChange={(e) => setValues({ ...values, [key]: String(e.target.checked) })} /> {label}
                </label>
              );
            }
            return (
              <Field key={key} label={label} htmlFor={id} hint={prop.description ?? (type === 'array' ? 'Comma-separated' : format === 'date-time' ? 'ISO 8601, e.g. 2026-01-01T00:00:00Z' : undefined)}>
                <input
                  id={id}
                  className={inputClass}
                  type={type === 'number' || type === 'integer' ? 'number' : 'text'}
                  step="any"
                  value={values[key] ?? ''}
                  placeholder={prop.default !== undefined && prop.default !== null ? String(prop.default) : ''}
                  onChange={(e) => setValues({ ...values, [key]: e.target.value })}
                />
              </Field>
            );
          })}
        </div>
        {error !== undefined && <ErrorState error={error} />}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" busy={busy}>
            {rule ? 'Save changes' : 'Create rule'}
          </Button>
          <Button onClick={onCancel}>Cancel</Button>
          {info && <Badge tone="info">scope: {info.scope}</Badge>}
        </div>
      </form>
    </Card>
  );
}
