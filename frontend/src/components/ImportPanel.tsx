import { useState, type FormEvent } from 'react';
import { api } from '../api/client';
import type { Dataset, ImportResponse } from '../api/types';
import { Badge, Button, ErrorState, Field } from './ui';
import { formatNumber, inputClass } from '../lib/format';

const ACCEPT = '.csv,.tsv,.json,.jsonl,.ndjson';

export function ImportPanel({ datasets, onImported }: { datasets: Dataset[]; onImported: (result: ImportResponse) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [target, setTarget] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [result, setResult] = useState<ImportResponse>();

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) {
      setError(new Error('Choose a CSV, JSON or JSON Lines file first.'));
      return;
    }
    const form = new FormData();
    form.append('file', file);
    if (target) form.append('dataset_id', target);
    else if (name.trim()) form.append('dataset_name', name.trim());
    setBusy(true);
    setError(undefined);
    setResult(undefined);
    try {
      const response = await api.importDataset(form);
      setResult(response);
      onImported(response);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" aria-label="Import dataset">
      <div className="grid gap-4 md:grid-cols-3">
        <Field label="File" htmlFor="import-file" hint="CSV, TSV, JSON array, or JSON Lines. Parsed safely; never executed.">
          <input id="import-file" type="file" accept={ACCEPT} className="text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        <Field label="Import as" htmlFor="import-target" hint="A new version keeps every earlier version intact.">
          <select id="import-target" className={inputClass} value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">New dataset</option>
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                New version of {d.name}
              </option>
            ))}
          </select>
        </Field>
        {!target && (
          <Field label="Dataset name (optional)" htmlFor="import-name" hint="Defaults to the file name.">
            <input id="import-name" className={inputClass} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="e.g. orders" />
          </Field>
        )}
      </div>
      <div>
        <Button type="submit" variant="primary" busy={busy}>
          Import
        </Button>
      </div>
      {error !== undefined && <ErrorState error={error} />}
      {result && <ImportSummaryView result={result} />}
    </form>
  );
}

export function ImportSummaryView({ result }: { result: ImportResponse }) {
  const s = result.summary;
  return (
    <div role="status" className="rounded-lg border border-good/30 bg-good/5 p-4 text-sm">
      <p className="font-medium text-good-ink">
        ✓ Imported {result.dataset.name} version {result.version.version_number}: {formatNumber(s.rows_accepted)} rows × {s.columns} columns
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Badge tone={s.rows_rejected ? 'serious' : 'good'}>{s.rows_rejected} rejected rows</Badge>
        <Badge tone={s.duplicate_rows ? 'warning' : 'neutral'}>{s.duplicate_rows} duplicate rows</Badge>
        <Badge>{s.missing_cells} missing cells</Badge>
        <Badge tone={s.invalid_cells ? 'warning' : 'neutral'}>{s.invalid_cells} invalid cells</Badge>
        <Badge>encoding {s.encoding}</Badge>
        {Object.entries(s.type_counts).map(([type, count]) => (
          <Badge key={type} tone="info">
            {count} {type}
          </Badge>
        ))}
      </div>
      {s.warnings.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-ink-2">
          {s.warnings.slice(0, 8).map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {s.rejected_rows.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-ink-2">Rejected rows ({s.rows_rejected})</summary>
          <ul className="mt-1 space-y-1 font-mono text-xs">
            {s.rejected_rows.slice(0, 20).map((r) => (
              <li key={r.line}>
                line {r.line}: {r.reason} {r.preview && <span className="text-ink-3">— {r.preview}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
