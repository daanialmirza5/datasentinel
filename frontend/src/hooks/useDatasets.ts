import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { useAsync } from './useAsync';

/** Selected dataset lives in the URL (?dataset=…) so pages deep-link and share the selection. */
export function useSelectedDataset(): [string | null, (id: string | null) => void] {
  const [params, setParams] = useSearchParams();
  const selected = params.get('dataset');
  const setSelected = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set('dataset', id);
    else next.delete('dataset');
    setParams(next, { replace: true });
  };
  return [selected, setSelected];
}

export function useDatasets() {
  return useAsync(() => api.datasets({ limit: 200 }), []);
}
