import { useEffect } from 'react';
import type { Dataset } from '../api/types';
import { inputClass } from '../lib/format';

export function DatasetPicker({ datasets, value, onChange, id = 'dataset-picker', autoSelect = true }: { datasets: Dataset[]; value: string | null; onChange: (id: string) => void; id?: string; autoSelect?: boolean }) {
  const first = datasets[0]?.id;
  useEffect(() => {
    if (autoSelect && first && (!value || !datasets.some((d) => d.id === value))) onChange(first);
  }, [autoSelect, first, value, datasets, onChange]);
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-sm font-medium text-ink-2">
        Dataset
      </label>
      <select id={id} className={`${inputClass} min-w-48`} value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
        {!value && <option value="">Select a dataset…</option>}
        {datasets.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name} {d.current_version ? `(v${d.current_version.version_number})` : ''}
          </option>
        ))}
      </select>
    </div>
  );
}
